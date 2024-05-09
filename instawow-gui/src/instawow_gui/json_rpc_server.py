from __future__ import annotations

import asyncio
import contextvars
import enum
import importlib.resources
import json
import os
from collections.abc import Callable, Iterator, Set
from contextlib import AsyncExitStack, contextmanager
from datetime import datetime
from functools import partial
from itertools import chain
from pathlib import Path
from typing import Any, Literal, TypeVar

import aiohttp
import aiohttp.typedefs
import aiohttp.web
import anyio.from_thread
import attrs
import cattrs
import cattrs.preconf.json
from aiohttp_rpc import JsonRpcMethod
from aiohttp_rpc import middlewares as rpc_middlewares
from aiohttp_rpc.errors import InvalidParams, ServerError
from aiohttp_rpc.server import WsJsonRpcServer
from typing_extensions import ParamSpec, TypedDict
from yarl import URL

from instawow import __version__, matchers, pkg_management, pkg_models, shared_ctx
from instawow import results as R
from instawow._logging import logger
from instawow._progress_reporting import ReadOnlyProgressGroup, make_progress_receiver
from instawow._utils.aio import cancel_tasks, gather, run_in_thread
from instawow._utils.datetime import datetime_fromisoformat
from instawow._utils.file import reveal_folder
from instawow._utils.iteration import WeakValueDefaultDictionary, uniq
from instawow._utils.web import open_url
from instawow._version_check import is_outdated
from instawow.catalogue.cataloguer import ComputedCatalogueEntry
from instawow.catalogue.search import search
from instawow.config import GlobalConfig, ProfileConfig, SecretStr, config_converter
from instawow.definitions import Defn, SourceMetadata, Strategies
from instawow.github_auth import get_codes, poll_for_access_token
from instawow.http import init_web_client
from instawow.wow_installations import Flavour, infer_flavour_from_addon_dir

from . import frontend

_T = TypeVar('_T')
_P = ParamSpec('_P')

_toga_handle = contextvars.ContextVar[tuple[Any, anyio.from_thread.BlockingPortal]]('_toga_handle')

_LOCK_PREFIX = object()


class _LockOperation(tuple[object, str], enum.Enum):
    ModifyProfile = (_LOCK_PREFIX, '_MODIFY_PROFILE_')
    UpdateGlobalConfig = (_LOCK_PREFIX, '_UPDATE_GLOBAL_CONFIG')
    InitiateGithubAuthFlow = (_LOCK_PREFIX, '_INITIATE_GITHUB_AUTH_FLOW_')


LOCALHOST = '127.0.0.1'

_converter = cattrs.Converter(
    unstruct_collection_overrides={
        Set: sorted,
    }
)
cattrs.preconf.json.configure_converter(_converter)
_converter.register_structure_hook(Path, lambda v, _: Path(v))
_converter.register_structure_hook(datetime, lambda v, _: datetime_fromisoformat(v))
_converter.register_structure_hook(Strategies, lambda v, _: Strategies(v))
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


@run_in_thread
def _read_global_config() -> GlobalConfig:
    with _reraise_validation_errors(_ConfigError):
        return GlobalConfig.read().ensure_dirs()


@run_in_thread
def _read_profile_config(global_config: GlobalConfig, profile: str) -> ProfileConfig:
    with _reraise_validation_errors(_ConfigError):
        return ProfileConfig.read(global_config, profile).ensure_dirs()


_methods: list[tuple[str, type[BaseParams]]] = []


def _register_method(method: str):
    def inner(param_class: type[BaseParams]):
        _methods.append((method, param_class))
        return attrs.frozen(slots=False)(param_class)

    return inner


@attrs.frozen(slots=False)
class _ProfileParamMixin:
    profile: str


@attrs.frozen(slots=False)
class _DefnParamMixin:
    defns: list[Defn]


class BaseParams:
    @classmethod
    def bind(cls, method: str, config_ctxs: _ConfigBoundCtxCollection) -> JsonRpcMethod:
        async def respond(**kwargs: Any):
            with _reraise_validation_errors(InvalidParams, kwargs):
                self = _converter.structure(kwargs, cls)
            return await self.respond(config_ctxs)

        return JsonRpcMethod(respond, name=method)

    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> Any:
        raise NotImplementedError


@_register_method('config/write_profile')
class WriteProfileConfigParams(_ProfileParamMixin, BaseParams):
    addon_dir: Path
    game_flavour: Flavour
    infer_game_flavour: bool

    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> ProfileConfig:
        async with config_ctxs.locks[(*_LockOperation.ModifyProfile, self.profile)]:
            with _reraise_validation_errors(_ConfigError):
                config = config_converter.structure(
                    {
                        'global_config': await _read_global_config(),
                        'profile': self.profile,
                        'addon_dir': self.addon_dir,
                        'game_flavour': self.game_flavour,
                    },
                    ProfileConfig,
                )
                if self.infer_game_flavour:
                    config = attrs.evolve(
                        config,
                        game_flavour=infer_flavour_from_addon_dir(config.addon_dir)
                        or Flavour.Retail,
                    )
                await run_in_thread(config.write)()

            # Unload the corresponding ``Manager`` instance for the
            # config to be reloaded on the next request
            await config_ctxs.unload(config.profile)

            return config


@_register_method('config/read_profile')
class ReadProfileConfigParams(_ProfileParamMixin, BaseParams):
    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> ProfileConfig:
        return await _read_profile_config(config_ctxs.global_config, self.profile)


@_register_method('config/delete_profile')
class DeleteProfileConfigParams(_ProfileParamMixin, BaseParams):
    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> None:
        config_ctx = await config_ctxs.load(self.profile)

        async with config_ctxs.locks[(*_LockOperation.ModifyProfile, self.profile)]:
            await run_in_thread(config_ctx.config.delete)()
            await config_ctxs.unload(self.profile)


@_register_method('config/list_profiles')
class ListProfilesParams(BaseParams):
    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> list[str]:
        return await run_in_thread(list[str])(config_ctxs.global_config.iter_profiles())


@_register_method('config/update_global')
class UpdateGlobalConfigParams(BaseParams):
    access_tokens: dict[str, str | None]

    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> GlobalConfig:
        def update_global_config_cb(global_config: GlobalConfig):
            return attrs.evolve(
                global_config,
                access_tokens=attrs.evolve(
                    global_config.access_tokens,
                    **{k: t if t is None else SecretStr(t) for k, t in self.access_tokens.items()},
                ),
            )

        return await config_ctxs.update_global_config(update_global_config_cb)


@_register_method('config/read_global')
class ReadGlobalConfigParams(BaseParams):
    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> GlobalConfig:
        return await _read_global_config()


class GithubCodesResponse(TypedDict):
    user_code: str
    verification_uri: str


@_register_method('config/initiate_github_auth_flow')
class InitiateGithubAuthFlowParams(BaseParams):
    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> GithubCodesResponse:
        return await config_ctxs.initiate_github_auth_flow()


class GithubAuthFlowStatusResponse(TypedDict):
    status: Literal['success', 'failure']


@_register_method('config/query_github_auth_flow_status')
class QueryGithubAuthFlowStatusParams(BaseParams):
    async def respond(
        self, config_ctxs: _ConfigBoundCtxCollection
    ) -> GithubAuthFlowStatusResponse:
        return {'status': await config_ctxs.wait_for_github_auth_completion()}


@_register_method('config/cancel_github_auth_flow')
class CancelGithubAuthFlowParams(BaseParams):
    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> None:
        await config_ctxs.cancel_github_auth_polling()


@_register_method('sources/list')
class ListSourcesParams(_ProfileParamMixin, BaseParams):
    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> dict[str, SourceMetadata]:
        config_ctx = await config_ctxs.load(self.profile)
        return {r.metadata.id: r.metadata for r in config_ctx.resolvers.values()}


@_register_method('list')
class ListInstalledParams(_ProfileParamMixin, BaseParams):
    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> list[pkg_models.Pkg]:
        config_ctx = await config_ctxs.load(self.profile)

        with config_ctx.database.connect() as connection:
            return [
                pkg_models.build_pkg_from_row_mapping(connection, p)
                for p in connection.execute('SELECT * FROM pkg ORDER BY lower(name)')
            ]


@_register_method('search')
class SearchParams(_ProfileParamMixin, BaseParams):
    search_terms: str
    limit: int
    sources: set[str]
    start_date: datetime | None
    installed_only: bool

    async def respond(
        self, config_ctxs: _ConfigBoundCtxCollection
    ) -> list[ComputedCatalogueEntry]:
        config_ctx = await config_ctxs.load(self.profile)

        return await search(
            config_ctx,
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
    async def respond(
        self, config_ctxs: _ConfigBoundCtxCollection
    ) -> list[SuccessResult | ErrorResult]:
        config_ctx = await config_ctxs.load(self.profile)

        def extract_source(defn: Defn):
            if not defn.source:
                match = pkg_management.get_alias_from_url(config_ctx, defn.alias)
                if match:
                    source, alias = match
                    defn = attrs.evolve(defn, source=source, alias=alias)
            return defn

        results = await pkg_management.resolve(config_ctx, list(map(extract_source, self.defns)))
        return [
            {'status': 'success', 'addon': r}
            if isinstance(r, pkg_models.Pkg)
            else {'status': r.status, 'message': r.message}
            for r in results.values()
        ]


@_register_method('install')
class InstallParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    replace: bool

    async def respond(
        self, config_ctxs: _ConfigBoundCtxCollection
    ) -> list[SuccessResult | ErrorResult]:
        config_ctx = await config_ctxs.load(self.profile)

        results = await pkg_management.install(
            config_ctx, self.defns, replace_folders=self.replace
        )
        return [
            {'status': r.status, 'addon': r.pkg}
            if isinstance(r, R.PkgInstalled)
            else {'status': r.status, 'message': r.message}
            for r in results.values()
        ]


@_register_method('update')
class UpdateParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    async def respond(
        self, config_ctxs: _ConfigBoundCtxCollection
    ) -> list[SuccessResult | ErrorResult]:
        config_ctx = await config_ctxs.load(self.profile)

        results = await pkg_management.update(config_ctx, self.defns)
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

    async def respond(
        self, config_ctxs: _ConfigBoundCtxCollection
    ) -> list[SuccessResult | ErrorResult]:
        config_ctx = await config_ctxs.load(self.profile)

        results = await pkg_management.remove(
            config_ctx, self.defns, keep_folders=self.keep_folders
        )
        return [
            {'status': r.status, 'addon': r.old_pkg}
            if isinstance(r, R.PkgRemoved)
            else {'status': r.status, 'message': r.message}
            for r in results.values()
        ]


@_register_method('pin')
class PinParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    async def respond(
        self, config_ctxs: _ConfigBoundCtxCollection
    ) -> list[SuccessResult | ErrorResult]:
        config_ctx = await config_ctxs.load(self.profile)

        results = await pkg_management.pin(config_ctx, self.defns)
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

    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> str:
        config_ctx = await config_ctxs.load(self.profile)

        return await pkg_management.get_changelog(
            config_ctx, source=self.source, uri=self.changelog_url
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

    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> list[AddonMatch]:
        config_ctx = await config_ctxs.load(self.profile)

        leftovers = await run_in_thread(matchers.get_unreconciled_folders)(config_ctx)

        match_groups = await matchers.DEFAULT_MATCHERS[self.matcher](
            config_ctx, leftovers=leftovers
        )

        resolved_defns = await pkg_management.resolve(
            config_ctx, uniq(d for _, b in match_groups for d in b)
        )
        pkgs, _ = pkg_management.bucketise_results(resolved_defns.items())

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
    async def respond(
        self, config_ctxs: _ConfigBoundCtxCollection
    ) -> list[ReconcileInstalledCandidate]:
        config_ctx = await config_ctxs.load(self.profile)

        with config_ctx.database.connect() as connection:
            installed_pkgs = [
                pkg_models.build_pkg_from_row_mapping(connection, p)
                for p in connection.execute('SELECT * FROM pkg ORDER BY lower(name)')
            ]

        defn_groups = await pkg_management.find_equivalent_pkg_defns(config_ctx, installed_pkgs)
        resolved_defns = await pkg_management.resolve(
            config_ctx, uniq(d for b in defn_groups.values() for d in b)
        )
        pkgs, _ = pkg_management.bucketise_results(resolved_defns.items())
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
    async def respond(
        self, config_ctxs: _ConfigBoundCtxCollection
    ) -> list[DownloadProgressReport]:
        config_ctx = await config_ctxs.load(self.profile)

        return [
            {'defn': p['defn'], 'progress': p['current'] / p['total']}
            for p in config_ctxs.current_progress.values()
            if p['type_'] == 'pkg_download'
            and p['total']
            and p['profile'] == config_ctx.config.profile
        ]


class GetVersionResult(TypedDict):
    installed_version: str
    new_version: str | None


@_register_method('meta/get_version')
class GetVersionParams(BaseParams):
    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> GetVersionResult:
        outdated, new_version = await is_outdated(config_ctxs.global_config)
        return {
            'installed_version': __version__,
            'new_version': new_version if outdated else None,
        }


@_register_method('assist/open_url')
class OpenUrlParams(BaseParams):
    url: str

    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> None:
        open_url(self.url)


@_register_method('assist/reveal_folder')
class RevealFolderParams(BaseParams):
    path_parts: list[str]

    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> None:
        reveal_folder(os.path.join(*self.path_parts))


class SelectFolderResult(TypedDict):
    selection: Path | None


@_register_method('assist/select_folder')
class SelectFolderParams(BaseParams):
    initial_folder: str | None

    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> SelectFolderResult:
        main_window, portal = _toga_handle.get()

        async def select_folder() -> Path | None:
            return await main_window.select_folder_dialog('Select folder', self.initial_folder)

        try:
            selection = portal.call(select_folder)
        except ValueError:
            selection = None
        return {'selection': selection}


class ConfirmDialogueResult(TypedDict):
    ok: bool


@_register_method('assist/confirm')
class ConfirmDialogueParams(BaseParams):
    title: str
    message: str

    async def respond(self, config_ctxs: _ConfigBoundCtxCollection) -> ConfirmDialogueResult:
        main_window, portal = _toga_handle.get()

        async def confirm() -> bool:
            return await main_window.confirm_dialog(self.title, self.message)

        return {'ok': portal.call(confirm)}


class _ConfigBoundCtxCollection:
    def __init__(self):
        self.locks = WeakValueDefaultDictionary[object, asyncio.Lock](asyncio.Lock)

        self._config_ctxs = dict[str, shared_ctx.ConfigBoundCtx]()

        self.current_progress: ReadOnlyProgressGroup[pkg_management.PkgDownloadProgress] = {}

        self._github_auth_device_codes = None
        self._github_auth_flow_task = None

    async def __aenter__(self):
        self._exit_stack = AsyncExitStack()

        self.global_config = await _read_global_config()

        self._web_client = await self._exit_stack.enter_async_context(
            init_web_client(self.global_config.http_cache_dir, with_progress=True)
        )

        iter_progress = self._exit_stack.enter_context(
            make_progress_receiver[pkg_management.PkgDownloadProgress]()
        )

        async def update_progress():
            async for progress_group in iter_progress:
                self.current_progress = progress_group

        progress_updater = asyncio.create_task(update_progress())
        self._exit_stack.push_async_callback(partial(cancel_tasks, [progress_updater]))

        self._exit_stack.push_async_callback(self.cancel_github_auth_polling)

        shared_ctx.locks_var.set(self.locks)
        shared_ctx.web_client_var.set(self._web_client)

    async def __aexit__(self, *args: object):
        await self._exit_stack.aclose()

    async def load(self, profile: str) -> shared_ctx.ConfigBoundCtx:
        try:
            config_ctx = self._config_ctxs[profile]
        except KeyError:
            async with self.locks[(*_LockOperation.ModifyProfile, profile)]:
                try:
                    config_ctx = self._config_ctxs[profile]
                except KeyError:
                    config_ctx = self._config_ctxs[profile] = shared_ctx.ConfigBoundCtx(
                        await _read_profile_config(self.global_config, profile)
                    )

        return config_ctx

    async def unload(self, profile: str) -> None:
        if profile in self._config_ctxs:
            config_ctx = self._config_ctxs[profile]
            await run_in_thread(config_ctx.__exit__)(*((None,) * 3))
            del self._config_ctxs[profile]

    async def _unload_all(self):
        await gather(self.unload(p) for p in self._config_ctxs)

    async def update_global_config(
        self, update_cb: Callable[[GlobalConfig], GlobalConfig]
    ) -> GlobalConfig:
        async with self.locks[_LockOperation.UpdateGlobalConfig]:
            with _reraise_validation_errors(_ConfigError):
                self.global_config = update_cb(self.global_config)
                await run_in_thread(self.global_config.write)()

            await self._unload_all()

            return self.global_config

    async def initiate_github_auth_flow(self):
        async with self.locks[_LockOperation.InitiateGithubAuthFlow]:
            if self._github_auth_device_codes is None:

                async def finalise_github_auth_flow():
                    result = await poll_for_access_token(
                        self._web_client, codes['device_code'], codes['interval']
                    )

                    def update_global_config_cb(global_config: GlobalConfig):
                        return attrs.evolve(
                            global_config,
                            access_tokens=attrs.evolve(
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

    async def cancel_github_auth_polling(self):
        if self._github_auth_flow_task:
            await cancel_tasks([self._github_auth_flow_task])


async def create_app(toga_handle: tuple[Any, anyio.from_thread.BlockingPortal] | None = None):
    if toga_handle:
        _toga_handle.set(toga_handle)

    frontend_resources = importlib.resources.files(frontend)

    config_ctxs = _ConfigBoundCtxCollection()

    async def config_ctxs_listen(app: aiohttp.web.Application):
        async with config_ctxs:
            yield

    async def get_index(request: aiohttp.web.Request):
        return aiohttp.web.Response(
            content_type='text/html',
            text=frontend_resources.joinpath('index.html').read_text(),
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
            text=frontend_resources.joinpath(filename).read_text(),
        )

    def json_serialize(value: dict[str, Any]):
        return json.dumps(_converter.unstructure(value))

    rpc_server = WsJsonRpcServer(
        json_serialize=json_serialize,
        middlewares=rpc_middlewares.DEFAULT_MIDDLEWARES,  # pyright: ignore[reportUnknownMemberType]
    )
    rpc_server.add_methods(  # pyright: ignore[reportUnknownMemberType]
        [m.bind(n, config_ctxs) for n, m in _methods]
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
                r'/assets/{name}{extension:(?:\.css|\.js(?:\.map)?)}', get_static_file
            ),
            aiohttp.web.get('/api', rpc_server.handle_http_request),
        ]
    )
    app.cleanup_ctx.append(config_ctxs_listen)
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
