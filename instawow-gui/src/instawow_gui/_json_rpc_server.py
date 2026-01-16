from __future__ import annotations

import asyncio
import contextvars
import enum
import importlib.resources
import json
import os
from collections.abc import Awaitable, Callable, Iterator, Set
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from datetime import datetime
from inspect import get_annotations
from itertools import chain
from pathlib import Path
from typing import Any, Literal, NotRequired, Union, cast

import aiohttp
import aiohttp.typedefs
import aiohttp.web
import attrs
import cattrs
import cattrs.preconf.json
import cattrs.strategies
import toga
from typing_extensions import TypedDict
from yarl import URL

from instawow import _github_auth, config_ctx, http_ctx, matchers, pkg_management, sync_ctx
from instawow import results as R
from instawow._logging import logger
from instawow._utils.aio import cancel_tasks, run_in_thread
from instawow._utils.attrs import evolve
from instawow._utils.iteration import WeakValueDefaultDictionary, uniq
from instawow.catalogue.cataloguer import CatalogueEntry
from instawow.catalogue.search import search as search_catalogue
from instawow.config import GlobalConfig, ProfileConfig, SecretStr, config_converter
from instawow.definitions import Defn, SourceMetadata, Strategies
from instawow.http import init_web_client
from instawow.pkg_archives._download import PkgDownloadProgress
from instawow.pkg_db import models as pkg_models
from instawow.progress_reporting import ReadOnlyProgressGroup, make_progress_receiver

_toga_handle_var = contextvars.ContextVar[toga.App]('_toga_handle_var')


@attrs.define(kw_only=True)
class _GlobalCtx:
    global_config: GlobalConfig
    profiles: dict[str, config_ctx.ConfigParty]
    get_progress: Callable[[], ReadOnlyProgressGroup[PkgDownloadProgress]]
    github_auth_manager: _GitHubAuthManager


_global_ctx_var = contextvars.ContextVar[_GlobalCtx]('_global_ctx_var')


_LOCK_PREFIX = object()


class _LockOperation(tuple[object, str], enum.Enum):
    ModifyProfile = (_LOCK_PREFIX, '_MODIFY_PROFILE_')
    UpdateGlobalConfig = (_LOCK_PREFIX, '_UPDATE_GLOBAL_CONFIG')
    InitiateGitHubAuthFlow = (_LOCK_PREFIX, '_INITIATE_GITHUB_AUTH_FLOW_')


LOCALHOST = '127.0.0.1'


class _JsonRpcRequest[MethodT: str, ParamsT](TypedDict):
    jsonrpc: Literal['2.0']
    method: MethodT
    params: ParamsT
    id: int | str


class _JsonRpcSuccessResponse[ResultT](TypedDict):
    jsonrpc: Literal['2.0']
    result: ResultT
    id: int | str


class _JsonRpcErrorResponse(TypedDict):
    jsonrpc: Literal['2.0']
    error: _JsonRpcError
    id: int | str | None


class _JsonRpcError(TypedDict):
    code: int
    message: str
    data: NotRequired[list[Any]]


type _MethodResponder = Callable[..., Awaitable[object]]

_methods = dict[str, tuple[type[_JsonRpcRequest[Any, Any]], _MethodResponder]]()


def _register_method(method: str):
    def wrapper[MethodResponderT: Callable[..., Awaitable[object]]](
        method_responder: MethodResponderT,
    ) -> MethodResponderT:
        params = get_annotations(method_responder)
        params.pop('return', None)

        request_type = _JsonRpcRequest[
            Literal[method],  # pyright: ignore[reportInvalidTypeArguments]
            TypedDict('params', params) if params else NotRequired[Any],  # pyright: ignore[reportArgumentType]
        ]
        request_type.__name__ = method

        _methods[method] = (request_type, method_responder)
        return method_responder

    return wrapper


class _SuccessResult[T](TypedDict):
    status: Literal['success']
    addon: T


class _ErrorResult(TypedDict):
    status: Literal['failure', 'error']
    message: str


@_register_method('config/list_profiles')
async def list_profiles() -> dict[str, ProfileConfig]:
    global_ctx = _global_ctx_var.get()

    profiles = await run_in_thread(list[str])(
        ProfileConfig.iter_profiles(global_ctx.global_config)
    )

    async def get_profile_configs():
        for profile in profiles:
            try:
                profile_config = await _read_profile_config(global_ctx.global_config, profile)
            except Exception:
                continue
            else:
                yield (profile, profile_config)

    return {p: c async for p, c in get_profile_configs()}


@_register_method('config/write_profile')
async def write_profile_config(profile: str, addon_dir: Path) -> ProfileConfig:
    async with sync_ctx.locks()[*_LockOperation.ModifyProfile, profile]:
        config = config_converter.structure(
            {
                'global_config': _global_ctx_var.get().global_config,
                'profile': profile,
                'addon_dir': addon_dir,
            },
            ProfileConfig,
        )
        await run_in_thread(config.write)()

        # Profile will be reloaded on the next request.
        _unload_profiles(config.profile)

        return config


@_register_method('config/delete_profile')
async def delete_profile(profile: str) -> None:
    async with _load_profile(profile) as config_party:
        async with sync_ctx.locks()[*_LockOperation.ModifyProfile, profile]:
            await run_in_thread(config_party.config.delete)()
            _unload_profiles(profile)


@_register_method('config/read_global')
async def read_global_config() -> GlobalConfig:
    return _global_ctx_var.get().global_config


@_register_method('config/update_global')
async def update_global_config(access_tokens: dict[str, str | None]) -> GlobalConfig:
    return await _update_global_config(
        lambda g: evolve(
            g,
            {
                'access_tokens': {
                    k: t if t is None else SecretStr(t) for k, t in access_tokens.items()
                },
            },
        )
    )


@_register_method('config/initiate_github_auth_flow')
async def initiate_github_auth_flow() -> TypedDict[{'user_code': str, 'verification_uri': str}]:
    return await _global_ctx_var.get().github_auth_manager.initiate_auth_flow()


@_register_method('config/query_github_auth_flow_status')
async def query_github_auth_flow_status() -> TypedDict[{'status': Literal['success', 'failure']}]:
    return {'status': await _global_ctx_var.get().github_auth_manager.await_auth_completion()}


@_register_method('sources/list')
async def list_sources(profile: str) -> dict[str, SourceMetadata]:
    async with _load_profile(profile) as config_party:
        return {r.metadata.id: r.metadata for r in config_party.resolvers.values()}


@_register_method('list')
async def list_installed_pkgs(profile: str) -> list[pkg_models.Pkg]:
    async with _load_profile(profile) as config_party:
        with config_party.database as connection:
            return [
                pkg_management.build_pkg_from_row_mapping(connection, r)
                for r in connection.execute('SELECT * FROM pkg ORDER BY lower(name)')
            ]


@_register_method('search')
async def search_pkgs(
    profile: str,
    search_terms: str,
    limit: int,
    sources: set[str],
    start_date: datetime | None,
    installed_only: bool,
) -> list[CatalogueEntry]:
    async with _load_profile(profile):
        return await search_catalogue(
            search_terms,
            limit=limit,
            sources=sources,
            start_date=start_date,
            filter_installed='include_only' if installed_only else 'ident',
        )


@_register_method('resolve')
async def resolve_pkgs(
    profile: str, defns: list[Defn]
) -> list[_SuccessResult[pkg_models.Pkg] | _ErrorResult]:
    async with _load_profile(profile):

        def extract_source(defn: Defn):
            if not defn.source:
                match = pkg_management.get_alias_from_url(defn.alias)
                if match:
                    source, alias = match
                    defn = evolve(defn, {'source': source, 'alias': alias})
            return defn

        results = await pkg_management.resolve(list(map(extract_source, defns)))
        return [
            {
                'status': 'success',
                'addon': pkg_management.build_pkg_from_pkg_candidate(d, r, folders=[]),
            }
            if isinstance(r, dict)
            else {'status': r.status, 'message': str(r)}
            for d, r in results.items()
        ]


@_register_method('install')
async def install_pkgs(
    profile: str, defns: list[Defn], replace: bool
) -> list[_SuccessResult[pkg_models.Pkg] | _ErrorResult]:
    async with _load_profile(profile):
        results = await pkg_management.install(defns, replace_folders=replace)
        return [
            {'status': r.status, 'addon': r.pkg}
            if isinstance(r, R.PkgInstalled)
            else {'status': r.status, 'message': str(r)}
            for r in results.values()
        ]


@_register_method('update')
async def update_pkgs(
    profile: str, defns: list[Defn]
) -> list[_SuccessResult[pkg_models.Pkg] | _ErrorResult]:
    async with _load_profile(profile):
        results = await pkg_management.update(defns)
        return [
            {'status': r.status, 'addon': r.new_pkg}
            if isinstance(r, R.PkgUpdated)
            else {'status': r.status, 'addon': r.pkg}
            if isinstance(r, R.PkgInstalled)
            else {'status': r.status, 'message': str(r)}
            for r in results.values()
        ]


@_register_method('remove')
async def remove_pkgs(
    profile: str, defns: list[Defn], keep_folders: bool
) -> list[_SuccessResult[pkg_models.Pkg] | _ErrorResult]:
    async with _load_profile(profile):
        results = await pkg_management.remove(defns, keep_folders=keep_folders)
        return [
            {'status': r.status, 'addon': r.old_pkg}
            if isinstance(r, R.PkgRemoved)
            else {'status': r.status, 'message': str(r)}
            for r in results.values()
        ]


@_register_method('pin')
async def pin_pkgs(
    profile: str, defns: list[Defn]
) -> list[_SuccessResult[pkg_models.Pkg] | _ErrorResult]:
    async with _load_profile(profile):
        results = await pkg_management.pin(defns)
        return [
            {'status': r.status, 'addon': r.pkg}
            if isinstance(r, R.PkgInstalled)
            else {'status': r.status, 'message': str(r)}
            for r in results.values()
        ]


@_register_method('get_changelog')
async def get_pkg_changelog(profile: str, source: str, changelog_url: str) -> str:
    async with _load_profile(profile):
        return await pkg_management.get_changelog(source=source, url=changelog_url)


@_register_method('get_logged_versions')
async def get_pkg_logged_versions(profile: str, defn: Defn) -> list[pkg_models.PkgLoggedVersion]:
    async with _load_profile(profile):
        (pkg,) = pkg_management.get_pkgs((defn,))
        return pkg_management.get_pkg_logged_versions(pkg) if pkg else []


@_register_method('reconcile')
async def reconcile_pkgs(
    profile: str, matcher: str
) -> list[
    TypedDict[
        {
            'folders': list[TypedDict[{'name': str, 'version': str}]],
            'matches': list[pkg_models.Pkg],
        }
    ]
]:
    async with _load_profile(profile):
        leftovers = await run_in_thread(matchers.get_unreconciled_folders)()

        match_groups = await matchers.DEFAULT_MATCHERS[matcher](leftovers)

        resolved_defns = await pkg_management.resolve(uniq(d for _, b in match_groups for d in b))
        pkg_candidates, _ = pkg_management.split_results(resolved_defns.items())

        matched_folders = (
            (
                g,
                [
                    pkg_management.build_pkg_from_pkg_candidate(d, i, folders=[])
                    for d in s
                    for i in (pkg_candidates.get(d),)
                    if i
                ],
            )
            for g, s in match_groups
        )
        unmatched_folders = (
            ([a], list[pkg_models.Pkg]())
            for a in sorted(leftovers - frozenset(i for a, _ in matched_folders for i in a))
        )
        return [
            {
                'folders': [{'name': f.name, 'version': f.toc_reader.version} for f in a],
                'matches': m,
            }
            for a, m in chain(matched_folders, unmatched_folders)
        ]


@_register_method('get_reconcile_installed_candidates')
async def get_reconcile_installed_pkg_candidates(
    profile: str,
) -> list[
    TypedDict[{'installed_addon': pkg_models.Pkg, 'alternative_addons': list[pkg_models.Pkg]}]
]:
    async with _load_profile(profile) as config_party:
        with config_party.database as connection:
            installed_pkgs = [
                pkg_management.build_pkg_from_row_mapping(connection, p)
                for p in connection.execute('SELECT * FROM pkg ORDER BY lower(name)')
            ]

        defn_groups = await pkg_management.find_equivalent_pkg_defns(installed_pkgs)

        resolved_defns = await pkg_management.resolve(
            uniq(d for b in defn_groups.values() for d in b)
        )
        pkg_candidates, _ = pkg_management.split_results(resolved_defns.items())

        return [
            {'installed_addon': p, 'alternative_addons': m}
            for p, s in defn_groups.items()
            for m in (
                [
                    pkg_management.build_pkg_from_pkg_candidate(d, i, folders=[])
                    for d in s
                    for i in (pkg_candidates.get(d),)
                    if i
                ],
            )
            if m
        ]


@_register_method('get_download_progress')
async def respond(profile: str) -> list[TypedDict[{'defn': Defn, 'progress': float}]]:
    async with _load_profile(profile) as config_party:
        global_ctx = _global_ctx_var.get()
        return [
            {'defn': p['defn'], 'progress': p['current'] / p['total']}
            for p in global_ctx.get_progress().values()
            if p['type_'] == 'pkg_download'
            and p['total']
            and p['profile'] == config_party.config.profile
        ]


@_register_method('meta/get_version')
async def get_instawow_version() -> TypedDict[
    {'installed_version': str, 'new_version': str | None}
]:
    from instawow._version import get_version, is_outdated

    installed_version = get_version()
    new_version = None

    global_ctx = _global_ctx_var.get()
    if global_ctx.global_config.auto_update_check:
        outdated, maybe_new_version = await is_outdated(installed_version)
        if outdated:
            new_version = maybe_new_version

    return {'installed_version': installed_version, 'new_version': new_version}


@_register_method('assist/open_url')
@run_in_thread
def open_url(url: str) -> None:
    from instawow._utils.web import open_url

    open_url(url)


@_register_method('assist/reveal_folder')
@run_in_thread
def reveal_folder(path_parts: list[str]) -> None:
    from instawow._utils.file import reveal_folder

    reveal_folder(os.path.join(*path_parts))


@_register_method('assist/select_folder')
@run_in_thread
def select_folder(initial_folder: str | None) -> TypedDict[{'selection': Path | None}]:
    app = _toga_handle_var.get()

    async def select_folder():
        try:
            assert isinstance(app.main_window, toga.Window)
            return await app.main_window.dialog(
                toga.SelectFolderDialog('Select folder', initial_folder),
            )
        except ValueError:
            return None

    future = asyncio.run_coroutine_threadsafe(select_folder(), app.loop)
    return {'selection': future.result()}


@_register_method('assist/confirm')
@run_in_thread
def prompt_confirm(title: str, message: str) -> TypedDict[{'ok': bool}]:
    app = _toga_handle_var.get()

    async def confirm():
        assert isinstance(app.main_window, toga.Window)
        return await app.main_window.dialog(
            toga.ConfirmDialog(title, message),
        )

    future = asyncio.run_coroutine_threadsafe(confirm(), app.loop)
    return {'ok': future.result()}


class _GitHubAuthManager(AbstractAsyncContextManager['_GitHubAuthManager']):
    def __init__(self):
        self._device_codes = None
        self._finalisation_task = asyncio.create_task(asyncio.sleep(0))

    async def __aexit__(self, *args: object):
        await cancel_tasks([self._finalisation_task])

    async def initiate_auth_flow(self):
        async with sync_ctx.locks()[_LockOperation.InitiateGitHubAuthFlow]:
            if self._device_codes is None:
                web_client = http_ctx.web_client()

                self._device_codes = device_codes = await _github_auth.get_codes(web_client)

                async def finalise_github_auth_flow():
                    result = await _github_auth.poll_for_access_token(
                        web_client,
                        device_codes['device_code'],
                        device_codes['interval'],
                    )
                    await _update_global_config(
                        lambda g: evolve(g, {'access_tokens': {'github': SecretStr(result)}})
                    )

                finalisation_task = asyncio.create_task(
                    asyncio.wait_for(finalise_github_auth_flow(), timeout=5 * 60),
                )

                @finalisation_task.add_done_callback
                def _(task: asyncio.Task[None]):
                    self._device_codes = None

                self._finalisation_task = finalisation_task

        return self._device_codes

    async def await_auth_completion(self):
        try:
            await self._finalisation_task
        except BaseException:
            return 'failure'
        else:
            return 'success'


@run_in_thread
def _read_global_config() -> GlobalConfig:
    return GlobalConfig.read().ensure_dirs()


@run_in_thread
def _read_profile_config(global_config: GlobalConfig, profile: str) -> ProfileConfig:
    return ProfileConfig.read(global_config, profile).ensure_dirs()


@asynccontextmanager
async def _load_profile(profile: str):
    global_ctx = _global_ctx_var.get()

    try:
        config_party = global_ctx.profiles[profile]
    except KeyError:
        async with sync_ctx.locks()[*_LockOperation.ModifyProfile, profile]:
            try:
                config_party = global_ctx.profiles[profile]
            except KeyError:
                config_party = global_ctx.profiles[profile] = config_ctx.ConfigParty.from_config(
                    await _read_profile_config(global_ctx.global_config, profile)
                )

    config_ctx.config.set(config_party)

    with logger.contextualize(profile=config_party.config.profile):
        yield config_party


def _unload_profiles(*profiles: str):
    global_ctx = _global_ctx_var.get()
    for profile in profiles or list(global_ctx.profiles):
        if profile in global_ctx.profiles:
            del global_ctx.profiles[profile]


async def _update_global_config(update: Callable[[GlobalConfig], GlobalConfig]):
    async with sync_ctx.locks()[_LockOperation.UpdateGlobalConfig]:
        global_config = update(await _read_global_config())
        await run_in_thread(global_config.write)()

        global_ctx = _global_ctx_var.get()
        global_ctx.global_config = global_config
        _unload_profiles()

        return global_config


_converter = cattrs.Converter(
    unstruct_collection_overrides={
        Set: sorted,
    },
)
cattrs.preconf.json.configure_converter(_converter)
_converter.register_structure_hook(Path, lambda v, t: Path(v))
_converter.register_structure_hook(Strategies, lambda v, t: Strategies(v))
_converter.register_unstructure_hook(Path, str)
_converter.register_unstructure_hook(Strategies, dict)

_method_union = cast(type[_JsonRpcRequest[str, Any]], Union[*(t for t, _ in _methods.values())])

_method_converter = _converter.copy()
cattrs.strategies.configure_tagged_union(_method_union, _method_converter, tag_name='method')


def _transform_validation_errors(
    exc: cattrs.ClassValidationError | cattrs.IterableValidationError | BaseException,
    path: tuple[str | int, ...] = (),
) -> Iterator[TypedDict[{'path': tuple[str | int, ...], 'message': str}]]:
    match exc:
        case cattrs.IterableValidationError():
            excs_with_notes, excs_without_notes = exc.group_exceptions()
            for exc, new_path in chain(
                ((e, (*path, n.index)) for e, n in excs_with_notes),
                ((e, path) for e in excs_without_notes),
            ):
                yield from _transform_validation_errors(exc, new_path)

        case cattrs.ClassValidationError():
            excs_with_notes, excs_without_notes = exc.group_exceptions()
            for exc, new_path in chain(
                ((e, (*path, n.name)) for e, n in excs_with_notes),
                ((e, path) for e in excs_without_notes),
            ):
                yield from _transform_validation_errors(exc, new_path)

        case _:
            yield {
                'path': path,
                'message': repr(exc),
            }


async def create_web_app(toga_handle: toga.App | None = None):
    from . import _frontend

    frontend_resources = importlib.resources.files(_frontend)

    websockets = set[aiohttp.web.WebSocketResponse]()

    async def close_websockets(app: aiohttp.web.Application):
        for websocket in websockets:
            await websocket.close(code=aiohttp.WSCloseCode.GOING_AWAY, message=b'server shutdown')

    async def ctxify(app: aiohttp.web.Application):
        async with AsyncExitStack() as exit_stack:
            sync_ctx.locks.set(
                WeakValueDefaultDictionary[object, asyncio.Lock](asyncio.Lock),
            )

            global_config = await _read_global_config()

            web_client = await exit_stack.enter_async_context(
                init_web_client(global_config.dirs.cache, with_progress=True)
            )
            http_ctx.web_client.set(web_client)

            get_progress, _ = exit_stack.enter_context(
                make_progress_receiver[PkgDownloadProgress]()
            )

            github_auth_manager = await exit_stack.enter_async_context(_GitHubAuthManager())

            if toga_handle:
                _toga_handle_var.set(toga_handle)

            _global_ctx_var.set(
                _GlobalCtx(
                    global_config=global_config,
                    profiles={},
                    get_progress=get_progress,
                    github_auth_manager=github_auth_manager,
                )
            )

            yield

    async def get_index(request: aiohttp.web.Request):
        return aiohttp.web.Response(
            content_type='text/html',
            body=frontend_resources.joinpath('index.html').read_bytes(),
        )

    async def get_static_file(request: aiohttp.web.Request):
        filename = request.path.lstrip('/')

        if filename.endswith('.js'):
            content_type = 'application/javascript'
        elif filename.endswith('.js.map'):
            content_type = 'application/json'
        elif filename.endswith('.css'):
            content_type = 'text/css'
        else:
            raise aiohttp.web.HTTPNotFound

        return aiohttp.web.Response(
            content_type=content_type,
            body=frontend_resources.joinpath(filename).read_bytes(),
        )

    async def serve_json_rpc_api(request: aiohttp.web.Request):
        async def handle_json_rpc_request(msg: aiohttp.WSMessage):
            try:
                json_rpc_request_json = msg.json()
            except json.JSONDecodeError:
                response = _JsonRpcErrorResponse(
                    jsonrpc='2.0',
                    error=_JsonRpcError(code=-32700, message='parse error'),
                    id=None,
                )
                return await websocket.send_json(response)

            try:
                json_rpc_request = _converter.structure(
                    json_rpc_request_json, _JsonRpcRequest[str, Any]
                )
            except cattrs.BaseValidationError as error:
                validation_errors = list(_transform_validation_errors(error))
                response = _JsonRpcErrorResponse(
                    jsonrpc='2.0',
                    error=_JsonRpcError(
                        code=-32600, message='invalid request', data=validation_errors
                    ),
                    id=json_rpc_request_json.get('id'),
                )
                return await websocket.send_json(response)

            try:
                qualified_json_rpc_request = _method_converter.structure(
                    json_rpc_request, _method_union
                )
            except cattrs.BaseValidationError as error:
                validation_errors = list(_transform_validation_errors(error))
                response = _JsonRpcErrorResponse(
                    jsonrpc='2.0',
                    error=_JsonRpcError(
                        code=-32602, message='invalid params', data=validation_errors
                    ),
                    id=json_rpc_request_json['id'],
                )
                return await websocket.send_json(response)

            _, respond = _methods[qualified_json_rpc_request['method']]
            try:
                result = await respond(
                    # Our JSON-RPC client returns an empty array when params aren't specified.
                    **dict(qualified_json_rpc_request.get('params', []))
                )
            except BaseException as error:
                import traceback

                logger.exception('Unclassed error')

                response = _JsonRpcErrorResponse(
                    jsonrpc='2.0',
                    error=_JsonRpcError(
                        code=-32603,
                        message='internal error',
                        data=traceback.format_exception(error),
                    ),
                    id=qualified_json_rpc_request['id'],
                )
                return await websocket.send_json(response)

            response = _JsonRpcSuccessResponse(
                jsonrpc='2.0',
                result=_converter.unstructure(result),
                id=json_rpc_request['id'],
            )
            await websocket.send_json(response)

        websocket = aiohttp.web.WebSocketResponse()
        await websocket.prepare(request)
        websockets.add(websocket)

        tasks = set[asyncio.Task[object]]()  # To avoid tasks getting lost in the aether.

        async for msg in websocket:
            if msg.type == aiohttp.WSMsgType.TEXT:
                task = asyncio.create_task(handle_json_rpc_request(msg))
                tasks.add(task)
                task.add_done_callback(tasks.remove)

        return websocket

    @aiohttp.web.middleware
    async def enforce_same_origin(
        request: aiohttp.web.Request,
        handler: aiohttp.typedefs.Handler,
    ):
        if request.remote != LOCALHOST:
            raise aiohttp.web.HTTPUnauthorized

        if request.path.startswith('/api'):
            origin = request.headers.get(aiohttp.hdrs.ORIGIN)
            if origin is None:
                raise aiohttp.web.HTTPUnauthorized

            origin_url = URL(origin)
            if (
                origin_url.scheme != request.url.scheme
                or origin_url.host != request.url.host
                or origin_url.port != request.url.port
            ):
                raise aiohttp.web.HTTPUnauthorized

        return await handler(request)

    app = aiohttp.web.Application(middlewares=[enforce_same_origin])
    app.add_routes(
        [
            aiohttp.web.get('/', get_index),
            aiohttp.web.get(
                r'/assets/{name}{extension:(?:\.css|\.js(?:\.map)?)}', get_static_file
            ),
            aiohttp.web.get('/api', serve_json_rpc_api),
        ]
    )
    app.cleanup_ctx.append(ctxify)
    app.on_shutdown.append(close_websockets)
    app.freeze()
    return app


@asynccontextmanager
async def run_web_app(app: aiohttp.web.Application):
    "Fire up the server."
    app_runner = aiohttp.web.AppRunner(app)
    await app_runner.setup()
    assert app_runner.server  # Server is created during setup
    # By omitting the port ``loop.create_server`` will find an available port
    # to bind to - equivalent to creating a socket on port 0.
    server = await asyncio.get_running_loop().create_server(app_runner.server, LOCALHOST)
    host, port = server.sockets[0].getsockname()

    try:
        await server.start_serving()

        server_url = URL.build(scheme='http', host=host, port=port)
        logger.debug(f'JSON-RPC server running on {server_url}')
        yield server_url
    finally:
        # Fark knows how you're supposed to gracefully stop the server:
        #   https://github.com/aio-libs/aiohttp/issues/2950
        await app_runner.cleanup()
