from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from functools import partial
from itertools import starmap
import os
import typing
from typing import Any, TypeVar, overload
from uuid import uuid4

import aiohttp
import aiohttp.web
from aiohttp_rpc import JsonRpcMethod, WsJsonRpcServer, middlewares as rpc_middlewares
from aiohttp_rpc.errors import InvalidParams as InvalidParamsError, ServerError
from pydantic import BaseModel, ValidationError
from typing_extensions import Literal, TypeAlias, TypedDict
from yarl import URL

from . import __version__, results as R
from .config import Config
from .manager import Manager, init_web_client, prepare_database
from .matchers import (
    get_unreconciled_folder_set,
    match_addon_names_with_folder_names,
    match_folder_name_subsets,
    match_toc_source_ids,
)
from .models import Pkg, is_pkg
from .resolvers import CatalogueEntry, Defn, PkgModel, Strategy
from .utils import gather, is_outdated, run_in_thread as t, uniq

_T = TypeVar('_T')
ManagerWorkQueueItem: TypeAlias = (
    'tuple[asyncio.Future[Any], str, Callable[..., Awaitable[Any]] | None]'
)


LOCALHOST = '127.0.0.1'


class _ConfigError(ServerError):
    code = -32001
    message = 'invalid configuration parameters'


@contextmanager
def _reraise_validation_error(error_class: type[ServerError] = ServerError) -> Iterator[None]:
    try:
        yield
    except ValidationError as error:
        raise error_class(data=error.errors()) from error


class BaseParams(BaseModel):
    async def respond(self, managers: ManagerWorkQueue) -> Any:
        raise NotImplementedError


class _ProfileParamMixin(BaseModel):
    profile: str


class _DefnParamMixin(BaseModel):
    defns: typing.List[Defn]


class WriteConfigParams(BaseParams):
    values: typing.Dict[str, Any]
    infer_game_flavour: bool

    @t
    def respond(self, managers: ManagerWorkQueue) -> Config:
        with _reraise_validation_error(_ConfigError):
            config = Config(**self.values)
            if self.infer_game_flavour:
                config.game_flavour = Config.infer_flavour(config.addon_dir)
            config.write()

        # Dispose of the ``Manager`` corresponding to the profile if any
        # so that the configuration is reloaded on next invocation
        managers.unload_manager(config.profile)
        return config


class ReadConfigParams(_ProfileParamMixin, BaseParams):
    @t
    def respond(self, managers: ManagerWorkQueue) -> Config:
        with _reraise_validation_error(_ConfigError):
            return Config.read(self.profile)


class DeleteConfigParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: ManagerWorkQueue) -> None:
        async def delete_profile(manager: Manager):
            await t(manager.config.delete)()
            managers.unload_manager(self.profile)

        await managers.run(self.profile, delete_profile)


class ListProfilesParams(BaseParams):
    @t
    def respond(self, managers: ManagerWorkQueue) -> list[str]:
        return Config.list_profiles()


class Source(TypedDict):
    source: str
    name: str
    supported_strategies: list[Strategy]
    supports_rollback: bool
    changelog_format: str


class ListSourcesParams(_ProfileParamMixin, BaseParams):
    async def respond(self, managers: ManagerWorkQueue) -> list[Source]:
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
    async def respond(self, managers: ManagerWorkQueue) -> list[PkgModel]:
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

    async def respond(self, managers: ManagerWorkQueue) -> list[CatalogueEntry]:
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
    async def respond(self, managers: ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
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

    async def respond(self, managers: ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
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
    async def respond(self, managers: ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
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

    async def respond(self, managers: ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
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
    async def respond(self, managers: ManagerWorkQueue) -> list[SuccessResult | ErrorResult]:
        results = await managers.run(self.profile, partial(Manager.pin, defns=self.defns))
        return [
            SuccessResult(status=r.status, addon=PkgModel.from_orm(r.pkg))
            if isinstance(r, R.PkgInstalled)
            else ErrorResult(status=r.status, message=r.message)
            for r in results.values()
        ]


class GetChangelogParams(_ProfileParamMixin, BaseParams):
    changelog_url: str

    async def respond(self, managers: ManagerWorkQueue) -> str:
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


_matchers = {
    'toc_source_ids': match_toc_source_ids,
    'folder_name_subsets': match_folder_name_subsets,
    'addon_names_with_folder_names': match_addon_names_with_folder_names,
}


class ReconcileParams(_ProfileParamMixin, BaseParams):
    matcher: Literal['toc_source_ids', 'folder_name_subsets', 'addon_names_with_folder_names']

    async def respond(self, managers: ManagerWorkQueue) -> ReconcileResult:
        leftovers = await managers.run(self.profile, t(get_unreconciled_folder_set))
        match_groups = await managers.run(
            self.profile, partial(_matchers[self.matcher], leftovers=leftovers)
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
    async def respond(self, managers: ManagerWorkQueue) -> list[DownloadProgressReport]:
        manager = await managers.run(self.profile)
        return [
            DownloadProgressReport(defn=Defn.from_pkg(p), progress=s)
            for m, p, s in await gather(t() for t in managers.progress_reporters)
            if m is manager
        ]


class GetVersionResult(TypedDict):
    installed_version: str
    new_version: str | None


class GetVersionParams(BaseParams):
    async def respond(self, managers: ManagerWorkQueue) -> GetVersionResult:
        outdated, new_version = await is_outdated()
        return GetVersionResult(
            installed_version=__version__, new_version=new_version if outdated else None
        )


def _init_json_rpc_web_client(
    progress_reporters: set[Callable[[], Awaitable[tuple[Manager, Pkg, float]]]],
) -> aiohttp.ClientSession:
    from aiohttp import TraceConfig, TraceRequestEndParams, hdrs

    async def do_on_request_end(
        client_session: aiohttp.ClientSession,
        trace_config_ctx: Any,
        params: TraceRequestEndParams,
    ) -> None:
        trace_request_ctx = trace_config_ctx.trace_request_ctx
        if (
            not trace_request_ctx
            or 'manager' not in trace_request_ctx
            or 'pkg' not in trace_request_ctx
        ):
            return

        if not params.response.content_length or hdrs.CONTENT_ENCODING in params.response.headers:
            return

        content_length = params.response.content_length

        async def progress_reporter() -> tuple[Manager, Pkg, float]:
            total_bytes: int = params.response.content.total_bytes
            return (
                trace_request_ctx['manager'],
                trace_request_ctx['pkg'],
                total_bytes / content_length,
            )

        progress_reporters.add(progress_reporter)
        params.response.content.on_eof(lambda: progress_reporters.remove(progress_reporter))

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return init_web_client(trace_configs=[trace_config])


class ManagerWorkQueue:
    def __init__(self) -> None:
        self._managers: dict[str, Manager] = {}
        self._queue: asyncio.Queue[ManagerWorkQueueItem] = asyncio.Queue()
        self.progress_reporters: set[Callable[[], Awaitable[tuple[Manager, Pkg, float]]]] = set()
        self._web_client = _init_json_rpc_web_client(self.progress_reporters)
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def listen(self) -> None:
        Manager.contextualise(
            web_client=self._web_client,
            locks=self._locks,
        )

        while True:
            item = await self._queue.get()

            async def schedule(item: ManagerWorkQueueItem):
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
                except BaseException as error:
                    future.set_exception(error)
                else:
                    future.set_result(result)

            asyncio.create_task(schedule(item))
            self._queue.task_done()

    async def cleanup(self) -> None:
        await self._web_client.close()

    @overload
    async def run(self, profile: str, coro_fn: None = ...) -> Manager:
        ...

    @overload
    async def run(self, profile: str, coro_fn: Callable[..., Awaitable[_T]] = ...) -> _T:
        ...

    async def run(
        self, profile: str, coro_fn: Callable[..., Awaitable[_T]] | None = None
    ) -> Manager | _T:
        future: asyncio.Future[Any] = asyncio.Future()
        self._queue.put_nowait((future, profile, coro_fn))
        return await asyncio.wait_for(future, None)

    def unload_manager(self, profile: str) -> None:
        self._managers.pop(profile, None)


def _prepare_response(
    param_class: type[BaseParams], method: str, managers: ManagerWorkQueue
) -> JsonRpcMethod:
    async def respond(**kwargs: Any) -> BaseModel:
        with _reraise_validation_error(InvalidParamsError):
            params = param_class.parse_obj(kwargs)
        return await params.respond(managers)

    return JsonRpcMethod('', respond, custom_name=method)


def _serialise_response(value: dict[str, Any]) -> str:
    return BaseModel.construct(**value).json()


async def create_app() -> tuple[aiohttp.web.Application, str]:
    managers = ManagerWorkQueue()

    def start_managers():
        managers_listen = asyncio.create_task(managers.listen())

        async def on_shutdown(app: aiohttp.web.Application):
            managers_listen.cancel()
            await managers.cleanup()

        return on_shutdown

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
            ],
        )
    )
    endpoint = f'/{uuid4()}'
    app = aiohttp.web.Application()
    app.add_routes([aiohttp.web.get(endpoint, rpc_server.handle_http_request)])
    app.on_shutdown.append(start_managers())
    app.freeze()
    return (app, endpoint)


async def listen() -> None:
    "Fire up the server."
    loop = asyncio.get_running_loop()

    app, endpoint = await create_app()
    app_runner = aiohttp.web.AppRunner(app)
    await app_runner.setup()
    assert app_runner.server  # Server is created during ``app_runner.setup``
    # By omitting the port ``loop.create_server`` will find an available port
    # to bind to - equivalent to creating a socket on port 0.
    server = await loop.create_server(app_runner.server, LOCALHOST)
    assert server.sockets
    (host, port) = server.sockets[0].getsockname()
    message = str(URL.build(scheme='ws', host=host, port=port, path=endpoint)).encode()
    # We're writing the address to fd 3 in case something seeps into stdout
    for fd in (1, 3):
        os.write(fd, message)

    try:
        # ``server_forever`` cleans up after the server when it's interrupted
        await server.serve_forever()
    finally:
        await app_runner.cleanup()
