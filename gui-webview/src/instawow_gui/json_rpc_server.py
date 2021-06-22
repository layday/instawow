from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from functools import partial
import importlib.resources
from itertools import starmap
import os
from types import SimpleNamespace
import typing
from typing import Any, TypeVar, overload

import aiohttp
import aiohttp.web
from aiohttp_rpc import JsonRpcMethod, WsJsonRpcServer, middlewares as rpc_middlewares
from aiohttp_rpc.errors import InvalidParams as InvalidParamsError, ServerError
import click
from loguru import logger
from pydantic import BaseModel, ValidationError
from typing_extensions import Concatenate, Literal, ParamSpec, TypeAlias, TypedDict
from yarl import URL

from instawow import __version__, matchers, results as R
from instawow.config import Config
from instawow.manager import Manager, TraceRequestCtx, init_web_client, prepare_database
from instawow.models import Pkg, is_pkg
from instawow.resolvers import CatalogueEntry, Defn, PkgModel, Strategy
from instawow.utils import is_outdated, run_in_thread as t, uniq

from . import InstawowApp, frontend, templates

_T = TypeVar('_T')
_P = ParamSpec('_P')
_ManagerWorkQueueItem: TypeAlias = (
    'tuple[asyncio.Future[Any], str, Callable[..., Awaitable[Any]] | None]'
)


LOCALHOST = '127.0.0.1'


class _ConfigError(ServerError):
    code = -32001
    message = 'invalid configuration parameters'


@contextmanager
def _reraise_validation_error(
    error_class: type[ServerError | InvalidParamsError] = ServerError,
    values: dict[Any, Any] | None = None,
) -> Iterator[None]:
    try:
        yield
    except ValidationError as error:
        errors = error.errors()
        logger.info(f'received invalid request: {(values, errors)}')
        raise error_class(data=errors) from error


class BaseParams(BaseModel):
    async def respond(self, managers: _ManagerWorkQueue) -> Any:
        raise NotImplementedError


class _ProfileParamMixin(BaseModel):
    profile: str


class _DefnParamMixin(BaseModel):
    defns: typing.List[Defn]


class WriteConfigParams(BaseParams):
    values: typing.Dict[str, Any]
    infer_game_flavour: bool

    @t
    def respond(self, managers: _ManagerWorkQueue) -> Config:
        with _reraise_validation_error(_ConfigError):
            config = Config(**self.values)
            if self.infer_game_flavour:
                config.game_flavour = Config.infer_flavour(config.addon_dir)
            config.write()

        # Dispose of the ``Manager`` corresponding to the profile if any
        # so that the configuration is reloaded on next invocation
        managers.unload(config.profile)
        return config


class ReadConfigParams(_ProfileParamMixin, BaseParams):
    @t
    def respond(self, managers: _ManagerWorkQueue) -> Config:
        with _reraise_validation_error(_ConfigError):
            return Config.read(self.profile)


class DeleteConfigParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagerWorkQueue) -> None:
        async def delete_profile(manager: Manager):
            await t(manager.config.delete)()
            managers.unload(self.profile)

        await managers.run(self.profile, delete_profile)


class ListProfilesParams(BaseParams):
    @t
    def respond(self, managers: _ManagerWorkQueue) -> list[str]:
        return Config.list_profiles()


class Source(TypedDict):
    source: str
    name: str
    supported_strategies: list[Strategy]
    supports_rollback: bool
    changelog_format: str


class ListSourcesParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagerWorkQueue) -> list[Source]:
        manager = await managers.run(self.profile)
        return [
            Source(
                source=r.source,
                name=r.name,
                supported_strategies=sorted(r.strategies, key=list(Strategy).index),
                supports_rollback=r.supports_rollback,
                changelog_format=r.changelog_format.value,
            )
            for r in manager.resolvers.values()
        ]


class ListInstalledParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagerWorkQueue) -> list[PkgModel]:
        from sqlalchemy import func

        manager = await managers.run(self.profile)
        installed_pkgs = manager.database.query(Pkg).order_by(func.lower(Pkg.name)).all()
        return [PkgModel.from_orm(p) for p in installed_pkgs]


class SuccessResult(TypedDict):
    status: Literal['success']
    addon: PkgModel


class ErrorResult(TypedDict):
    status: Literal['failure', 'error']
    message: str


class SearchParams(_ProfileParamMixin, BaseParams):
    search_terms: str
    limit: int
    sources: typing.Optional[typing.Set[str]] = None

    async def respond(self, managers: _ManagerWorkQueue) -> list[CatalogueEntry]:
        return await managers.run(
            self.profile,
            partial(
                Manager.search,
                search_terms=self.search_terms,
                limit=self.limit,
                sources=self.sources,
            ),
        )


class ResolveParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    async def respond(self, managers: _ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
        def extract_source(manager: Manager, defns: list[Defn]):
            for defn in defns:
                if defn.source == '*':
                    pair = manager.pair_uri(defn.alias)
                    if pair:
                        source, alias = pair
                        defn = defn.with_(source=source, alias=alias)
                yield defn

        results = await managers.run(
            self.profile,
            partial(
                Manager.resolve,
                defns=list(extract_source(await managers.run(self.profile), self.defns)),
            ),
        )
        return [
            SuccessResult(status='success', addon=PkgModel.from_orm(r))
            if is_pkg(r)
            else ErrorResult(status=r.status, message=r.message)
            for r in results.values()
        ]


class InstallParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    replace: bool

    async def respond(self, managers: _ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(
            self.profile, partial(Manager.install, defns=self.defns, replace=self.replace)
        )
        return [
            SuccessResult(status=r.status, addon=PkgModel.from_orm(r.pkg))
            if isinstance(r, R.PkgInstalled)
            else ErrorResult(status=r.status, message=r.message)
            for r in results.values()
        ]


class UpdateParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    async def respond(self, managers: _ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(
            self.profile, partial(Manager.update, defns=self.defns, retain_strategy=True)
        )
        return [
            SuccessResult(status=r.status, addon=PkgModel.from_orm(r.new_pkg))
            if isinstance(r, R.PkgUpdated)
            else ErrorResult(status=r.status, message=r.message)
            for r in results.values()
        ]


class RemoveParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    keep_folders: bool

    async def respond(self, managers: _ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(
            self.profile, partial(Manager.remove, defns=self.defns, keep_folders=self.keep_folders)
        )
        return [
            SuccessResult(status=r.status, addon=PkgModel.from_orm(r.old_pkg))
            if isinstance(r, R.PkgRemoved)
            else ErrorResult(status=r.status, message=r.message)
            for r in results.values()
        ]


class PinParams(_ProfileParamMixin, _DefnParamMixin, BaseParams):
    async def respond(self, managers: _ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(self.profile, partial(Manager.pin, defns=self.defns))
        return [
            SuccessResult(status=r.status, addon=PkgModel.from_orm(r.pkg))
            if isinstance(r, R.PkgInstalled)
            else ErrorResult(status=r.status, message=r.message)
            for r in results.values()
        ]


class GetChangelogParams(_ProfileParamMixin, BaseParams):
    changelog_url: str

    async def respond(self, managers: _ManagerWorkQueue) -> str:
        return await managers.run(
            self.profile, partial(Manager.get_changelog, uri=self.changelog_url)
        )


class ReconcileResult_AddonFolder(TypedDict):
    name: str
    version: str


class ReconcileResult_AddonMatch(TypedDict):
    folders: list[ReconcileResult_AddonFolder]
    matches: list[PkgModel]


class ReconcileResult(TypedDict):
    reconciled: list[ReconcileResult_AddonMatch]
    unreconciled: list[ReconcileResult_AddonMatch]


class ReconcileParams(_ProfileParamMixin, BaseParams):
    matcher: Literal['toc_source_ids', 'folder_name_subsets', 'addon_names_with_folder_names']

    async def respond(self, managers: _ManagerWorkQueue) -> ReconcileResult:
        leftovers = await managers.run(self.profile, t(matchers.get_unreconciled_folder_set))
        match_groups: matchers.FolderAndDefnPairs = await managers.run(
            self.profile, partial(getattr(matchers, f'match_{self.matcher}'), leftovers=leftovers)
        )
        uniq_defns = uniq(d for _, b in match_groups for d in b)
        resolve_results = await managers.run(
            self.profile, partial(Manager.resolve, defns=uniq_defns)
        )
        return ReconcileResult(
            reconciled=[
                ReconcileResult_AddonMatch(
                    folders=[
                        ReconcileResult_AddonFolder(name=f.name, version=f.version) for f in a
                    ],
                    matches=[
                        PkgModel.from_orm(r) for i in d for r in (resolve_results[i],) if is_pkg(r)
                    ],
                )
                for a, d in match_groups
            ],
            unreconciled=[
                ReconcileResult_AddonMatch(
                    folders=[ReconcileResult_AddonFolder(name=f.name, version=f.version)],
                    matches=[],
                )
                for f in sorted(leftovers - frozenset(i for a, _ in match_groups for i in a))
            ],
        )


class DownloadProgressReport(TypedDict):
    defn: Defn
    progress: float


class GetDownloadProgressParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: _ManagerWorkQueue) -> list[DownloadProgressReport]:
        return [
            DownloadProgressReport(defn=Defn.from_pkg(p), progress=r)
            for p, r in await managers.get_download_progress(self.profile)
        ]


class GetVersionResult(TypedDict):
    installed_version: str
    new_version: str | None


class GetVersionParams(BaseParams):
    async def respond(self, managers: _ManagerWorkQueue) -> GetVersionResult:
        outdated, new_version = await is_outdated()
        return GetVersionResult(
            installed_version=__version__, new_version=new_version if outdated else None
        )


class OpenUrlParams(BaseParams):
    url: str

    async def respond(self, managers: _ManagerWorkQueue) -> None:
        click.launch(self.url)


class RevealFolderParams(BaseParams):
    path_parts: typing.List[str]

    async def respond(self, managers: _ManagerWorkQueue) -> None:
        click.launch(os.path.join(*self.path_parts), locate=True)


class SelectFolderResult(TypedDict):
    selection: str | None


class SelectFolderParams(BaseParams):
    initial_folder: typing.Optional[str]

    async def respond(self, managers: _ManagerWorkQueue) -> SelectFolderResult:
        async def select_folder():
            try:
                (selection,) = InstawowApp.app.iw_window.select_folder_dialog(
                    'Select folder', self.initial_folder
                )
            except ValueError:
                selection = None
            return selection

        selection = asyncio.run_coroutine_threadsafe(
            select_folder(), InstawowApp.app.loop
        ).result()
        return SelectFolderResult(selection=selection)


class ConfirmDialogueResult(TypedDict):
    ok: bool


class ConfirmDialogueParams(BaseParams):
    title: str
    message: str

    async def respond(self, managers: _ManagerWorkQueue) -> ConfirmDialogueResult:
        async def confirm():
            return InstawowApp.app.iw_window.confirm_dialog(self.title, self.message)

        ok = asyncio.run_coroutine_threadsafe(confirm(), InstawowApp.app.loop).result()
        return ConfirmDialogueResult(ok=ok)


def _init_json_rpc_web_client(
    progress_reporters: set[tuple[Manager, Pkg, Callable[[], float]]],
) -> aiohttp.ClientSession:
    async def do_on_request_end(
        client_session: aiohttp.ClientSession,
        trace_config_ctx: SimpleNamespace,
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
                trace_request_ctx['manager'],
                trace_request_ctx['pkg'],
                lambda: content.total_bytes / content_length,  # type: ignore
            )
            progress_reporters.add(entry)
            content.on_eof(lambda: progress_reporters.remove(entry))

    trace_config = aiohttp.TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return init_web_client(trace_configs=[trace_config])


class _ManagerWorkQueue:
    def __init__(self) -> None:
        self._managers: dict[str, Manager] = {}
        self._queue: asyncio.Queue[_ManagerWorkQueueItem] = asyncio.Queue()
        self._progress_reporters: set[tuple[Manager, Pkg, Callable[[], float]]] = set()
        self._web_client = _init_json_rpc_web_client(self._progress_reporters)
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def cleanup(self) -> None:
        await self._web_client.close()

    async def listen(self) -> None:
        Manager.contextualise(web_client=self._web_client, locks=self._locks)

        while True:
            item = await self._queue.get()

            async def schedule(item: _ManagerWorkQueueItem):
                future, profile, coro_fn = item
                try:
                    async with self._locks[f"load profile '{profile}'"]:
                        try:
                            manager = self._managers[profile]
                        except KeyError:
                            with _reraise_validation_error(_ConfigError):
                                config = await t(Config.read)(profile)

                            manager = self._managers[profile] = Manager(
                                config=config,
                                database=await t(prepare_database)(config),
                            )

                    if coro_fn is None:
                        result = manager
                    else:
                        result = await coro_fn(manager)
                except BaseException as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(result)

            asyncio.create_task(schedule(item))
            self._queue.task_done()

    @overload
    async def run(
        self,
        profile: str,
        coro_fn: None = None,
    ) -> Manager:
        ...

    @overload
    async def run(
        self,
        profile: str,
        coro_fn: Callable[Concatenate[Manager, _P], Awaitable[_T]],
    ) -> _T:
        ...

    async def run(
        self,
        profile: str,
        coro_fn: Callable[Concatenate[Manager, _P], Awaitable[_T]] | None = None,
    ) -> _T | Manager:
        future: asyncio.Future[Any] = asyncio.Future()
        self._queue.put_nowait((future, profile, coro_fn))
        return await asyncio.wait_for(future, None)

    async def get_download_progress(self, profile: str) -> Iterator[tuple[Pkg, float]]:
        manager = await self.run(profile)
        return ((p, r()) for m, p, r in self._progress_reporters if m is manager)

    def unload(self, profile: str) -> None:
        self._managers.pop(profile, None)


def _prepare_response(
    param_class: type[BaseParams], method: str, managers: _ManagerWorkQueue
) -> JsonRpcMethod:
    async def respond(**kwargs: Any) -> BaseModel:
        with _reraise_validation_error(InvalidParamsError, kwargs):
            params = param_class.parse_obj(kwargs)
        return await params.respond(managers)

    return JsonRpcMethod('', respond, custom_name=method)


def _serialise_response(value: dict[str, Any]) -> str:
    return BaseModel.construct(**value).json()


async def create_app() -> aiohttp.web.Application:
    managers = _ManagerWorkQueue()

    def start_managers():
        managers_listen = asyncio.create_task(managers.listen())

        async def on_shutdown(app: aiohttp.web.Application):
            managers_listen.cancel()
            await managers.cleanup()

        return on_shutdown

    async def get_index(request: aiohttp.web.Request):
        return aiohttp.web.Response(
            content_type='text/html',
            text=importlib.resources.read_text(templates, 'index.html'),
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
            text=importlib.resources.read_text(frontend, filename),
        )

    app = aiohttp.web.Application()
    app.add_routes(
        [
            aiohttp.web.get('/', get_index),
            aiohttp.web.get(
                r'/svelte-bundle{extension:(?:\.css|\.js(?:\.map)?)}', get_static_file
            ),
        ]
    )

    rpc_server = WsJsonRpcServer(
        json_serialize=_serialise_response,
        middlewares=rpc_middlewares.DEFAULT_MIDDLEWARES,
    )
    rpc_server.add_methods(
        starmap(
            _prepare_response,
            [
                (WriteConfigParams, 'config/write', managers),
                (ReadConfigParams, 'config/read', managers),
                (DeleteConfigParams, 'config/delete', managers),
                (ListProfilesParams, 'config/list', managers),
                (ListSourcesParams, 'sources/list', managers),
                (ListInstalledParams, 'list', managers),
                (SearchParams, 'search', managers),
                (ResolveParams, 'resolve', managers),
                (InstallParams, 'install', managers),
                (UpdateParams, 'update', managers),
                (RemoveParams, 'remove', managers),
                (PinParams, 'pin', managers),
                (GetChangelogParams, 'get_changelog', managers),
                (ReconcileParams, 'reconcile', managers),
                (GetDownloadProgressParams, 'get_download_progress', managers),
                (GetVersionParams, 'meta/get_version', managers),
                (OpenUrlParams, 'assist/open_url', managers),
                (RevealFolderParams, 'assist/reveal_folder', managers),
                (SelectFolderParams, 'assist/select_folder', managers),
                (ConfirmDialogueParams, 'assist/confirm', managers),
            ],
        )
    )
    app.add_routes([aiohttp.web.get('/api', rpc_server.handle_http_request)])

    app.on_shutdown.append(start_managers())
    app.freeze()
    return app


async def prepare() -> tuple[URL, Callable[[], Awaitable[None]]]:
    "Fire up the server."
    app = await create_app()
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
