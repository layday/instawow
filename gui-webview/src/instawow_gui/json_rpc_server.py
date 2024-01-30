from __future__ import annotations

import asyncio
import contextvars
import json
import os
from collections.abc import Awaitable, Callable, Iterator, Set
from contextlib import AsyncExitStack, contextmanager
from datetime import datetime
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Any, Concatenate, Literal, TypeAlias, TypeVar

import aiohttp
import aiohttp.typedefs
import aiohttp.web
import anyio.from_thread
import cattrs
import click
import iso8601
import sqlalchemy as sa
from aiohttp_rpc import JsonRpcMethod
from aiohttp_rpc import middlewares as rpc_middlewares
from aiohttp_rpc.errors import InvalidParams, ServerError
from aiohttp_rpc.server import WsJsonRpcServer
from attrs import evolve, frozen
from cattrs.preconf.json import configure_converter
from loguru import logger
from typing_extensions import ParamSpec, TypedDict
from yarl import URL

from instawow import __version__, matchers, pkg_db, pkg_models
from instawow import results as R
from instawow._version import is_outdated
from instawow.catalogue.cataloguer import ComputedCatalogueEntry
from instawow.catalogue.search import search
from instawow.common import Defn, Flavour, SourceMetadata
from instawow.config import Config, GlobalConfig, SecretStr, config_converter
from instawow.github_auth import get_codes, poll_for_access_token
from instawow.http import TraceRequestCtx, init_web_client
from instawow.manager_ctx import LocksType, ManagerCtx, contextualise
from instawow.pkg_management import PkgManager, bucketise_results
from instawow.utils import (
    StrEnum,
    WeakValueDefaultDictionary,
    read_resource_as_text,
    reveal_folder,
    uniq,
)
from instawow.utils import run_in_thread as t
from instawow.wow_installations import infer_flavour_from_addon_dir

from . import frontend

_T = TypeVar('_T')
_P = ParamSpec('_P')
_ManagerBoundCoroFn: TypeAlias = Callable[Concatenate[PkgManager, _P], Awaitable[_T]]

_toga_handle = contextvars.ContextVar[tuple[Any, anyio.from_thread.BlockingPortal]]('_toga_handle')

_LOCK_PREFIX = object()


class _LockOperation(StrEnum):
    ModifyProfile = '_MODIFY_PROFILE_'
    UpdateGlobalConfig = '_UPDATE_GLOBAL_CONFIG'
    InitiateGithubAuthFlow = '_INITIATE_GITHUB_AUTH_FLOW_'


LOCALHOST = '127.0.0.1'

_converter = cattrs.Converter(
    unstruct_collection_overrides={
        Set: sorted,
    }
)
configure_converter(_converter)
_converter.register_structure_hook(Path, lambda v, _: Path(v))
_converter.register_structure_hook(datetime, lambda v, _: iso8601.parse_date(v))
_converter.register_unstructure_hook(Path, str)


class _ConfigError(ServerError):
    code = -32001
    message = 'invalid configuration parameters'


class _ValidationErrorResponse(TypedDict):
    path: tuple[str | int, ...]
    message: str


def _transform_validation_errors(
    exc: cattrs.ClassValidationError | cattrs.IterableValidationError | BaseException,
    path: tuple[str | int, ...] = (),
) -> Iterator[_ValidationErrorResponse]:
    match exc:
        case cattrs.IterableValidationError():
            with_notes, _ = exc.group_exceptions()
            for exc, note in with_notes:
                assert isinstance(note.index, str | int)  # Dummy assert for type checking.
                new_path = (*path, note.index)
                if isinstance(exc, cattrs.ClassValidationError | cattrs.IterableValidationError):
                    yield from _transform_validation_errors(exc, new_path)
                else:
                    yield {
                        'path': new_path,
                        'message': str(exc),
                    }
        case cattrs.ClassValidationError():
            with_notes, _ = exc.group_exceptions()
            for exc, note in with_notes:
                new_path = (*path, note.name)
                if isinstance(exc, cattrs.ClassValidationError | cattrs.IterableValidationError):
                    yield from _transform_validation_errors(exc, new_path)
                else:
                    yield {
                        'path': new_path,
                        'message': str(exc),
                    }
        case _:
            pass


@contextmanager
def _reraise_validation_errors(
    error_class: type[ServerError | InvalidParams] = ServerError,
    values: dict[Any, Any] | None = None,
) -> Iterator[None]:
    try:
        yield
    except BaseException as exc:
        logger.info(f'invalid request: {(values, exc)}')
        raise error_class(data=list(_transform_validation_errors(exc))) from exc


@t
def _read_global_config() -> GlobalConfig:
    with _reraise_validation_errors(_ConfigError):
        return GlobalConfig.read().ensure_dirs()


@t
def _read_config(global_config: GlobalConfig, profile: str) -> Config:
    with _reraise_validation_errors(_ConfigError):
        return Config.read(global_config, profile).ensure_dirs()


_methods: list[tuple[str, type[BaseParams]]] = []


def _register_method(method: str):
    def inner(param_class: type[BaseParams]):
        _methods.append((method, param_class))
        return frozen(slots=False)(param_class)

    return inner


@frozen(slots=False)
class _ProfileParamMixin:
    profile: str


@frozen(slots=False)
class _DefnParamMixin:
    defns: list[Defn]


class BaseParams:
    @classmethod
    def bind(cls, method: str, managers: _ManagersManager) -> JsonRpcMethod:
        async def respond(**kwargs: Any):
            with _reraise_validation_errors(InvalidParams, kwargs):
                self = _converter.structure(kwargs, cls)
            return await self.respond(managers)

        return JsonRpcMethod(respond, name=method)

    async def respond(self, managers: _ManagersManager) -> Any:
        raise NotImplementedError


@_register_method('config/write_profile')
class WriteProfileConfigParams(_ProfileParamMixin, BaseParams):
    addon_dir: Path
    game_flavour: Flavour
    infer_game_flavour: bool

    async def respond(self, managers: _ManagersManager) -> Config:
        async with managers.locks[_LOCK_PREFIX, _LockOperation.ModifyProfile, self.profile]:
            with _reraise_validation_errors(_ConfigError):
                config = config_converter.structure(
                    {
                        'global_config': await _read_global_config(),
                        'profile': self.profile,
                        'addon_dir': self.addon_dir,
                        'game_flavour': self.game_flavour,
                    },
                    Config,
                )
                if self.infer_game_flavour:
                    config = evolve(
                        config,
                        game_flavour=infer_flavour_from_addon_dir(config.addon_dir)
                        or Flavour.Retail,
                    )
                await t(config.write)()

            # Unload the corresponding ``Manager`` instance for the
            # config to be reloaded on the next request
            managers.unload_profile(config.profile)

            return config


@_register_method('config/read_profile')
class ReadProfileConfigParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagersManager) -> Config:
        return await _read_config(managers.global_config, self.profile)


@_register_method('config/delete_profile')
class DeleteProfileConfigParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagersManager) -> None:
        async def delete_profile(manager: PkgManager):
            await t(manager.ctx.config.delete)()
            managers.unload_profile(self.profile)

        await managers.run(self.profile, delete_profile)


@_register_method('config/list_profiles')
class ListProfilesParams(BaseParams):
    async def respond(self, managers: _ManagersManager) -> list[str]:
        return await t(managers.global_config.list_profiles)()


@_register_method('config/update_global')
class UpdateGlobalConfigParams(BaseParams):
    access_tokens: dict[str, str | None]

    async def respond(self, managers: _ManagersManager) -> GlobalConfig:
        def update_global_config_cb(global_config: GlobalConfig):
            return evolve(
                global_config,
                access_tokens=evolve(
                    global_config.access_tokens,
                    **{k: t if t is None else SecretStr(t) for k, t in self.access_tokens.items()},
                ),
            )

        return await managers.update_global_config(update_global_config_cb)


@_register_method('config/read_global')
class ReadGlobalConfigParams(BaseParams):
    async def respond(self, managers: _ManagersManager) -> GlobalConfig:
        return await _read_global_config()


class GithubCodesResponse(TypedDict):
    user_code: str
    verification_uri: str


@_register_method('config/initiate_github_auth_flow')
class InitiateGithubAuthFlowParams(BaseParams):
    async def respond(self, managers: _ManagersManager) -> GithubCodesResponse:
        return await managers.initiate_github_auth_flow()


class GithubAuthFlowStatusReport(TypedDict):
    status: Literal['success', 'failure']


@_register_method('config/query_github_auth_flow_status')
class QueryGithubAuthFlowStatusParams(BaseParams):
    async def respond(self, managers: _ManagersManager) -> GithubAuthFlowStatusReport:
        return {'status': await managers.wait_for_github_auth_completion()}


@_register_method('config/cancel_github_auth_flow')
class CancelGithubAuthFlowParams(BaseParams):
    async def respond(self, managers: _ManagersManager) -> None:
        managers.cancel_github_auth_polling()


@_register_method('sources/list')
class ListSourcesParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagersManager) -> dict[str, SourceMetadata]:
        manager = await managers.get_manager(self.profile)
        return {r.metadata.id: r.metadata for r in manager.ctx.resolvers.values()}


@_register_method('list')
class ListInstalledParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagersManager) -> list[pkg_models.Pkg]:
        manager = await managers.get_manager(self.profile)

        with manager.ctx.database.connect() as connection:
            installed_pkgs = (
                connection.execute(
                    sa.select(pkg_db.pkg).order_by(sa.func.lower(pkg_db.pkg.c.name))
                )
                .mappings()
                .all()
            )
            return [manager.build_pkg_from_row_mapping(connection, p) for p in installed_pkgs]


@_register_method('search')
class SearchParams(_ProfileParamMixin, BaseParams):
    search_terms: str
    limit: int
    sources: set[str]
    start_date: datetime | None
    installed_only: bool

    async def respond(self, managers: _ManagersManager) -> list[ComputedCatalogueEntry]:
        manager = await managers.get_manager(self.profile)
        return await search(
            manager.ctx,
            self.search_terms,
            limit=self.limit,
            sources=self.sources,
            start_date=self.start_date,
            filter_installed='include_only' if self.installed_only else 'ident',
        )


class SuccessResult(TypedDict):
    status: Literal['success']
    addon: pkg_models.Pkg


class ErrorResult(TypedDict):
    status: Literal['failure', 'error']
    message: str


@_register_method('resolve')
class ResolveParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    async def _resolve(self, manager: PkgManager):
        def extract_source(defn: Defn):
            if defn.is_unsourced:
                match = manager.pair_uri(defn.alias)
                if match:
                    source, alias = match
                    defn = evolve(defn, source=source, alias=alias)
            return defn

        return await manager.resolve(list(map(extract_source, self.defns)))

    async def respond(self, managers: _ManagersManager) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(self.profile, self._resolve)
        return [
            {'status': 'success', 'addon': r}
            if isinstance(r, pkg_models.Pkg)
            else {'status': r.status, 'message': r.message}
            for r in results.values()
        ]


@_register_method('install')
class InstallParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    replace: bool

    async def respond(self, managers: _ManagersManager) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(
            self.profile,
            partial(PkgManager.install, defns=self.defns, replace_folders=self.replace),
        )
        return [
            {'status': r.status, 'addon': r.pkg}
            if isinstance(r, R.PkgInstalled)
            else {'status': r.status, 'message': r.message}
            for r in results.values()
        ]


@_register_method('update')
class UpdateParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    async def respond(self, managers: _ManagersManager) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(
            self.profile, partial(PkgManager.update, defns=self.defns, retain_defn_strategy=True)
        )
        return [
            {'status': r.status, 'addon': r.new_pkg}
            if isinstance(r, R.PkgUpdated)
            else {'status': r.status, 'addon': r.pkg}
            if isinstance(r, R.PkgInstalled)
            else {'status': r.status, 'message': r.message}
            for r in results.values()
        ]


@_register_method('remove')
class RemoveParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    keep_folders: bool

    async def respond(self, managers: _ManagersManager) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(
            self.profile,
            partial(PkgManager.remove, defns=self.defns, keep_folders=self.keep_folders),
        )
        return [
            {'status': r.status, 'addon': r.old_pkg}
            if isinstance(r, R.PkgRemoved)
            else {'status': r.status, 'message': r.message}
            for r in results.values()
        ]


@_register_method('pin')
class PinParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    async def respond(self, managers: _ManagersManager) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(self.profile, partial(PkgManager.pin, defns=self.defns))
        return [
            {'status': r.status, 'addon': r.pkg}
            if isinstance(r, R.PkgInstalled)
            else {'status': r.status, 'message': r.message}
            for r in results.values()
        ]


@_register_method('get_changelog')
class GetChangelogParams(_ProfileParamMixin, BaseParams):
    source: str
    changelog_url: str

    async def respond(self, managers: _ManagersManager) -> str:
        return await managers.run(
            self.profile,
            partial(PkgManager.get_changelog, source=self.source, uri=self.changelog_url),
        )


class AddonMatch(TypedDict):
    folders: list[AddonMatch_AddonFolder]
    matches: list[pkg_models.Pkg]


class AddonMatch_AddonFolder(TypedDict):
    name: str
    version: str


@_register_method('reconcile')
class ReconcileParams(_ProfileParamMixin, BaseParams):
    matcher: str

    async def respond(self, managers: _ManagersManager) -> list[AddonMatch]:
        manager = await managers.get_manager(self.profile)

        leftovers = await t(matchers.get_unreconciled_folders)(manager.ctx)

        match_groups = await matchers.DEFAULT_MATCHERS[self.matcher](
            manager.ctx, leftovers=leftovers
        )

        resolved_defns = await manager.resolve(uniq(d for _, b in match_groups for d in b))
        pkgs, _ = bucketise_results(resolved_defns.items())

        matched_folders = [
            (a, [i for i in (pkgs.get(d) for d in s) if i]) for a, s in match_groups
        ]
        unmatched_folders = (
            ([a], list[pkg_models.Pkg]())
            for a in sorted(leftovers - frozenset(i for a, _ in matched_folders for i in a))
        )
        return [
            {'folders': [{'name': f.name, 'version': f.version} for f in a], 'matches': m}
            for a, m in chain(matched_folders, unmatched_folders)
        ]


class ReconcileInstalledCandidate(TypedDict):
    installed_addon: pkg_models.Pkg
    alternative_addons: list[pkg_models.Pkg]


@_register_method('get_reconcile_installed_candidates')
class GetReconcileInstalledCandidatesParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagersManager) -> list[ReconcileInstalledCandidate]:
        manager = await managers.get_manager(self.profile)

        with manager.ctx.database.connect() as connection:
            installed_pkgs = [
                manager.build_pkg_from_row_mapping(connection, p)
                for p in connection.execute(
                    sa.select(pkg_db.pkg).order_by(sa.func.lower(pkg_db.pkg.c.name))
                )
                .mappings()
                .all()
            ]

        defn_groups = await managers.run(
            self.profile, partial(PkgManager.find_equivalent_pkg_defns, pkgs=installed_pkgs)
        )
        resolved_defns = await managers.run(
            self.profile,
            partial(PkgManager.resolve, defns=uniq(d for b in defn_groups.values() for d in b)),
        )
        pkgs, _ = bucketise_results(resolved_defns.items())
        return [
            {'installed_addon': p, 'alternative_addons': m}
            for p, s in defn_groups.items()
            for m in ([i for i in (pkgs.get(d) for d in s) if i],)
            if m
        ]


class DownloadProgressReport(TypedDict):
    defn: Defn
    progress: float


@_register_method('get_download_progress')
class GetDownloadProgressParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagersManager) -> list[DownloadProgressReport]:
        return [
            {'defn': d, 'progress': r}
            for d, r in await managers.get_manager_download_progress(self.profile)
        ]


class GetVersionResult(TypedDict):
    installed_version: str
    new_version: str | None


@_register_method('meta/get_version')
class GetVersionParams(BaseParams):
    async def respond(self, managers: _ManagersManager) -> GetVersionResult:
        outdated, new_version = await is_outdated(managers.global_config)
        return {
            'installed_version': __version__,
            'new_version': new_version if outdated else None,
        }


@_register_method('assist/open_url')
class OpenUrlParams(BaseParams):
    url: str

    async def respond(self, managers: _ManagersManager) -> None:
        click.launch(self.url)


@_register_method('assist/reveal_folder')
class RevealFolderParams(BaseParams):
    path_parts: list[str]

    async def respond(self, managers: _ManagersManager) -> None:
        reveal_folder(os.path.join(*self.path_parts))


class SelectFolderResult(TypedDict):
    selection: Path | None


@_register_method('assist/select_folder')
class SelectFolderParams(BaseParams):
    initial_folder: str | None

    async def respond(self, managers: _ManagersManager) -> SelectFolderResult:
        main_window, portal = _toga_handle.get()

        async def select_folder() -> Path | None:
            return await main_window.select_folder_dialog('Select folder', self.initial_folder)

        try:
            selection = portal.start_task_soon(select_folder).result()
        except ValueError:
            selection = None
        return {'selection': selection}


class ConfirmDialogueResult(TypedDict):
    ok: bool


@_register_method('assist/confirm')
class ConfirmDialogueParams(BaseParams):
    title: str
    message: str

    async def respond(self, managers: _ManagersManager) -> ConfirmDialogueResult:
        main_window, portal = _toga_handle.get()

        async def confirm() -> bool:
            return await main_window.confirm_dialog(self.title, self.message)

        return {'ok': portal.start_task_soon(confirm).result()}


def _init_json_rpc_web_client(cache_dir: Path):
    async def do_on_request_end(
        client_session: aiohttp.ClientSession,
        trace_config_ctx: Any,
        params: aiohttp.TraceRequestEndParams,
    ) -> None:
        trace_request_ctx: TraceRequestCtx = trace_config_ctx.trace_request_ctx
        if (
            trace_request_ctx
            and trace_request_ctx['report_progress'] == 'pkg_download'
            and params.response.content_length
            and aiohttp.hdrs.CONTENT_ENCODING not in params.response.headers
        ):
            content = params.response.content
            content_length = params.response.content_length
            entry = (
                trace_request_ctx['profile'],
                trace_request_ctx['defn'],
                lambda: content.total_bytes / content_length,
            )
            progress_reporters.add(entry)
            content.on_eof(lambda: progress_reporters.remove(entry))

    progress_reporters: set[tuple[str, Defn, Callable[[], float]]] = set()

    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()

    return (init_web_client(cache_dir, trace_configs=[trace_config]), progress_reporters)


class _ManagersManager:
    def __init__(self):
        self._exit_stack = AsyncExitStack()

        self.locks: LocksType = WeakValueDefaultDictionary(asyncio.Lock)

        self._managers = dict[str, PkgManager]()

        self._github_auth_device_codes = None
        self._github_auth_flow_task = None

    async def __aenter__(self):
        self.global_config = await _read_global_config()
        init_json_rpc_web_client, self._download_progress_reporters = _init_json_rpc_web_client(
            self.global_config.http_cache_dir
        )
        self._web_client = await self._exit_stack.enter_async_context(init_json_rpc_web_client)
        contextualise(web_client=self._web_client, locks=self.locks)

    async def __aexit__(self, *args: object):
        self.cancel_github_auth_polling()
        await self._exit_stack.aclose()

    def unload_profile(self, profile: str):
        if profile in self._managers:
            del self._managers[profile]

    def _unload_all_profiles(self):
        self._managers.clear()

    async def update_global_config(
        self, update_cb: Callable[[GlobalConfig], GlobalConfig]
    ) -> GlobalConfig:
        async with self.locks[_LOCK_PREFIX, _LockOperation.UpdateGlobalConfig]:
            with _reraise_validation_errors(_ConfigError):
                self.global_config = update_cb(self.global_config)
                await t(self.global_config.write)()

            self._unload_all_profiles()

            return self.global_config

    async def run(self, profile: str, coro_fn: _ManagerBoundCoroFn[..., _T]) -> _T:
        try:
            manager = self._managers[profile]
        except KeyError:
            async with self.locks[_LOCK_PREFIX, _LockOperation.ModifyProfile, profile]:
                try:
                    manager = self._managers[profile]
                except KeyError:
                    manager_ctx = ManagerCtx.from_config(
                        await _read_config(self.global_config, profile)
                    )
                    manager = self._managers[profile] = PkgManager(manager_ctx)

        return await coro_fn(manager)

    async def get_manager(self, profile: str):
        async def get_manager(manager: PkgManager):
            return manager

        return await self.run(profile, get_manager)

    async def get_manager_download_progress(self, profile: str):
        manager = await self.get_manager(profile)
        return (
            (d, r())
            for m, d, r in self._download_progress_reporters
            if m == manager.ctx.config.profile
        )

    async def initiate_github_auth_flow(self):
        async with self.locks[_LOCK_PREFIX, _LockOperation.InitiateGithubAuthFlow]:
            if self._github_auth_device_codes is None:

                async def finalise_github_auth_flow():
                    result = await poll_for_access_token(
                        self._web_client, codes['device_code'], codes['interval']
                    )

                    def update_global_config_cb(global_config: GlobalConfig):
                        return evolve(
                            global_config,
                            access_tokens=evolve(
                                global_config.access_tokens, github=SecretStr(result)
                            ),
                        )

                    await self.update_global_config(update_global_config_cb)

                def on_task_complete(task: object):
                    self._github_auth_flow_task = None
                    self._github_auth_device_codes = None

                self._github_auth_device_codes = codes = await get_codes(self._web_client)
                self._github_auth_flow_task = asyncio.create_task(finalise_github_auth_flow())
                self._github_auth_flow_task.add_done_callback(on_task_complete)

        return self._github_auth_device_codes

    async def wait_for_github_auth_completion(self):
        if self._github_auth_flow_task is not None:
            try:
                await self._github_auth_flow_task
            except BaseException:
                return 'failure'
        return 'success'

    def cancel_github_auth_polling(self):
        if self._github_auth_flow_task is not None:
            self._github_auth_flow_task.cancel()


async def create_app(toga_handle: tuple[Any, anyio.from_thread.BlockingPortal] | None = None):
    if toga_handle:
        _toga_handle.set(toga_handle)

    managers = _ManagersManager()

    async def managers_listen(app: aiohttp.web.Application):
        async with managers:
            yield

    async def get_index(request: aiohttp.web.Request):
        return aiohttp.web.Response(
            content_type='text/html',
            text=read_resource_as_text(frontend, 'index.html'),
        )

    async def get_static_file(request: aiohttp.web.Request):
        filename = request.path.lstrip('/')
        if filename.startswith('svelte-bundle.js'):
            content_type = 'application/javascript'
        elif filename == 'svelte-bundle.css':
            content_type = 'text/css'
        else:
            raise aiohttp.web.HTTPNotFound

        return aiohttp.web.Response(
            content_type=content_type,
            text=read_resource_as_text(frontend, filename),
        )

    def json_serialize(value: dict[str, Any]):
        return json.dumps(_converter.unstructure(value))

    rpc_server = WsJsonRpcServer(
        json_serialize=json_serialize,
        middlewares=rpc_middlewares.DEFAULT_MIDDLEWARES,  # pyright: ignore[reportUnknownMemberType]
    )
    rpc_server.add_methods(  # pyright: ignore[reportUnknownMemberType]
        [m.bind(n, managers) for n, m in _methods]
    )

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
                r'/svelte-bundle{extension:(?:\.css|\.js(?:\.map)?)}', get_static_file
            ),
            aiohttp.web.get('/api', rpc_server.handle_http_request),
        ]
    )
    app.cleanup_ctx.append(managers_listen)
    app.freeze()
    return app


async def run_app(app: aiohttp.web.Application):
    "Fire up the server."
    app_runner = aiohttp.web.AppRunner(app)
    await app_runner.setup()
    assert app_runner.server  # Server is created during setup
    # By omitting the port ``loop.create_server`` will find an available port
    # to bind to - equivalent to creating a socket on port 0.
    server = await asyncio.get_running_loop().create_server(app_runner.server, LOCALHOST)
    host, port = server.sockets[0].getsockname()

    async def serve():
        try:
            # ``server_forever`` cleans up after the server when it's interrupted
            await server.serve_forever()
        finally:
            await app_runner.cleanup()

    return (
        URL.build(scheme='http', host=host, port=port),
        serve,
    )
