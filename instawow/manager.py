
from __future__ import annotations

__all__ = ('Manager', 'CliManager', 'WsManager')

import asyncio
from contextlib import asynccontextmanager
import contextvars as cv
from functools import partial
from itertools import chain, repeat
from pathlib import Path, PurePath
from shutil import move as _move
from tempfile import NamedTemporaryFile, mkdtemp
from typing import *
from zipfile import ZipFile

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import __db_version__
from . import exceptions as E
from .models import ModelBase, Pkg, PkgFolder, should_migrate
from .resolvers import CurseResolver, WowiResolver, TukuiResolver, InstawowResolver
from .utils import bucketise, cached_property, dict_merge, gather, make_progress_bar

if TYPE_CHECKING:
    from types import SimpleNamespace
    import aiohttp
    from .config import Config


_UA_STRING = 'instawow (https://github.com/layday/instawow)'

_loop: cv.ContextVar[asyncio.AbstractEventLoop] = cv.ContextVar('_loop')
_web_client: cv.ContextVar[aiohttp.ClientSession] = cv.ContextVar('_web_client')


def run_in_thread(fn: Callable) -> Callable[..., Awaitable]:
    return lambda *a, **k: _loop.get().run_in_executor(None, partial(fn, *a, **k))


AsyncZipFile = run_in_thread(ZipFile)
AsyncNamedTemporaryFile = partial(run_in_thread(NamedTemporaryFile),
                                  prefix='instawow-')
async_mkdtemp = partial(run_in_thread(mkdtemp), prefix='instawow-')
async_move = run_in_thread(_move)


@asynccontextmanager
async def open_temp_writer() -> AsyncGenerator[Tuple[Path, Callable], None]:
    fh = await AsyncNamedTemporaryFile(delete=False, suffix='.zip')
    try:
        yield (Path(fh.name), run_in_thread(fh.write))
    finally:
        await run_in_thread(fh.close)()


async def new_temp_dir() -> PurePath:
    return PurePath(await async_mkdtemp())


async def move(paths: Iterable[Path], dest: PurePath) -> None:
    for path in paths:
        logger.debug(f'moving {path} to {dest / path.name}')
        await async_move(str(path), str(dest))


class _Archive:

    def __init__(self, path: Path, delete_after: bool) -> None:
        self.path = path
        self.delete_after = delete_after

    async def __aenter__(self) -> None:
        self.zipfile = await AsyncZipFile(self.path)
        self.folders = {PurePath(p).parts[0] for p in self.zipfile.namelist()}

    async def __aexit__(self, *args) -> None:
        def exit():
            self.zipfile.close()
            if self.delete_after:
                self.path.unlink()

        await run_in_thread(exit)()

    async def extract(self, parent: Path) -> None:
        def extract() -> None:
            conflicts = self.folders & {f.name for f in parent.iterdir()}
            if conflicts:
                raise E.PkgConflictsWithUncontrolled(conflicts)
            self.zipfile.extractall(parent)

        await run_in_thread(extract)()


async def download_archive(url: str, *, chunk_size: int = 4096) -> _Archive:
    if url.startswith('file://'):
        from urllib.parse import unquote

        path = Path(unquote(url[7:]))
        return _Archive(path, False)
    else:
        async with _web_client.get().get(url, trace_request_ctx={'progress': True}) as response, \
                open_temp_writer() as (path, write):
            async for chunk in response.content.iter_chunked(chunk_size):
                await write(chunk)
        return _Archive(path, True)


def prepare_db_session(*, config: Config) -> sessionmaker:
    db_url = f"sqlite:///{config.config_dir / 'db.sqlite'}"
    engine = create_engine(db_url)
    ModelBase.metadata.create_all(engine)

    if should_migrate(engine, __db_version__):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from .migrations import make_config, stamp, upgrade

        with engine.begin() as conn:
            alembic_config = make_config(db_url)
            diff = compare_metadata(MigrationContext.configure(conn),
                                    ModelBase.metadata)
            if diff:
                logger.info(f'migrating database to {__db_version__}')
                upgrade(alembic_config, __db_version__)
            else:
                logger.info(f'stamping database with {__db_version__}')
                stamp(alembic_config, __db_version__)

    return sessionmaker(bind=engine)


async def init_web_client(**kwargs: Any) -> aiohttp.ClientSession:
    from aiohttp import ClientSession, TCPConnector

    kwargs = {'connector': TCPConnector(limit_per_host=10),
              'headers': {'User-Agent': _UA_STRING},
              'trust_env': True,
              **kwargs}
    return ClientSession(**kwargs)


class _ResolverDict(dict):

    RESOLVERS = {CurseResolver, WowiResolver, TukuiResolver, InstawowResolver}

    def __init__(self, manager: Manager) -> None:
        super().__init__((r.origin, r(manager=manager)) for r in self.RESOLVERS)

    def __missing__(self, key: Hashable) -> NoReturn:
        raise E.PkgOriginInvalid


_Uri = Tuple[str, str]


def _error_wrapper(error: E.ManagerError) -> Callable:
    async def error_out() -> NoReturn:
        raise error
    return error_out


class Manager:

    def __init__(self,
                 config: Config,
                 web_client_factory: Optional[Callable] = None) -> None:
        self.config = config
        self.web_client_factory = web_client_factory or init_web_client
        self.resolvers = _ResolverDict(self)
        self.db = prepare_db_session(config=self.config)()

    @property
    def web_client(self) -> aiohttp.ClientSession:
        return _web_client.get()

    def run(self, awaitable: Awaitable) -> Any:
        "Run ``awaitable`` inside an explicit context."
        def runner():
            async def arunner():
                async with (await self.web_client_factory()) as client:
                    _web_client.set(client)
                    return await awaitable

            _loop.set(asyncio.get_event_loop())
            return _loop.get().run_until_complete(arunner())

        return cv.copy_context().run(runner)

    def get(self, origin: str, id_or_slug: str) -> Pkg:
        "Retrieve a ``Pkg`` from the database."
        return (self.db.query(Pkg)
                .filter(Pkg.origin == origin,
                        (Pkg.id == id_or_slug) | (Pkg.slug == id_or_slug))
                .first())

    async def resolve(self, uris: Sequence[_Uri], strategy: str) -> Dict[_Uri, Any]:
        "Resolve a sequence of ``_Uri``s into packages."
        async def resolve(origin: str, ids: List[str], strategy: str) -> Any:
            return await self.resolvers[origin].resolve(ids, strategy=strategy)

        buckets = bucketise(uris, key=lambda v: v[0])
        results = await gather(resolve(o, [i[1] for i in v], strategy=strategy)
                               for o, v in buckets.items())
        pairs = chain.from_iterable(zip(d, r if isinstance(r, list) else repeat(r))
                                    for d, r in zip(buckets.values(), results))
        sorted_pairs = dict(sorted(pairs, key=lambda v: uris.index(v[0])))
        return sorted_pairs

    async def prep_install(self, uris: Sequence[_Uri],
                           strategy: str, replace: bool) -> Dict[_Uri, Coroutine]:
        "Retrieve packages to install."
        async def install(pkg: Pkg, archive: _Archive, replace: bool) -> E.PkgInstalled:
            async with archive:
                pkg.folders = [PkgFolder(name=f) for f in sorted(archive.folders)]
                conflicts = (self.db.query(PkgFolder)
                             .filter(PkgFolder.name.in_([f.name for f in pkg.folders]))
                             .first())
                if conflicts:
                    raise E.PkgConflictsWithInstalled(conflicts.pkg)

                if replace:
                    temp_dir = await new_temp_dir()
                    await move((self.config.addon_dir / f.name
                                for f in pkg.folders),
                               temp_dir)

                await archive.extract(self.config.addon_dir)

            self.db.add(pkg)
            self.db.commit()
            return E.PkgInstalled(pkg)

        candidates = [u for u in uris if not self.get(*u)]
        packages = await self.resolve(candidates, strategy)
        installables = [(k, v) for k, v in packages.items() if isinstance(v, Pkg)]
        archives = await gather(download_archive(p.download_url)
                                for _, p in installables)

        coros = {k: v() for k, v in
                 {**dict.fromkeys(uris, _error_wrapper(E.PkgAlreadyInstalled())),
                  **{k: _error_wrapper(v) for k, v in packages.items()},
                  **{k: (lambda p=p, a=a: install(p, a, replace))
                     for (k, p), a in zip(installables, archives)}}.items()}
        return coros

    async def prep_update(self, uris: Sequence[_Uri]) -> Dict[_Uri, Coroutine]:
        "Retrieve packages to update."
        async def update(old_pkg: Pkg, new_pkg: Pkg, archive: _Archive) -> E.PkgUpdated:
            async with archive:
                new_pkg.folders = [PkgFolder(name=f) for f in sorted(archive.folders)]
                filter_ = (PkgFolder.name.in_([f.name for f in new_pkg.folders]),
                           PkgFolder.pkg_origin != new_pkg.origin,
                           PkgFolder.pkg_id != new_pkg.id)
                conflicts = self.db.query(PkgFolder).filter(*filter_).first()
                if conflicts:
                    raise E.PkgConflictsWithInstalled(conflicts.pkg)

                temp_dir = await new_temp_dir()
                await move((self.config.addon_dir / f.name
                            for f in old_pkg.folders),
                           temp_dir)

                await archive.extract(self.config.addon_dir)

            with self.db.begin_nested():
                self.db.delete(old_pkg)
                self.db.add(new_pkg)
            return E.PkgUpdated(old_pkg, new_pkg)

        candidates = {u: p for u, p in ((u, self.get(*u)) for u in uris) if p}
        strategy_buckets = bucketise(candidates.items(),
                                     key=lambda v: v[1].options.strategy)
        packages = dict_merge(*await gather(self.resolve([u for u, _ in c], s)
                                            for s, c in strategy_buckets.items()))
        installables = [(k, v) for k, v in packages.items() if isinstance(v, Pkg)]
        updatables = [(k, v) for k, v in installables if v.file_id != candidates[k].file_id]
        archives = await gather(download_archive(p.download_url)
                                for _, p in updatables)

        coros = {k: v() for k, v in
                 {**dict.fromkeys(uris, _error_wrapper(E.PkgNotInstalled())),
                  **{k: _error_wrapper(v) for k, v in packages.items()},
                  **{k: _error_wrapper(E.PkgUpToDate()) for k, _ in installables},
                  **{k: (lambda k=k, p=p, a=a: update(candidates[k], p, a))
                     for (k, p), a in zip(updatables, archives)}}.items()}
        return coros

    async def prep_remove(self, uris: Sequence[_Uri]) -> Dict[_Uri, Coroutine]:
        "Prepare packages to remove."
        async def remove(pkg: Pkg) -> E.PkgRemoved:
            temp_dir = await new_temp_dir()
            await move((self.config.addon_dir / f.name for f in pkg.folders),
                    temp_dir)

            self.db.delete(pkg)
            self.db.commit()
            return E.PkgRemoved(pkg)

        coros = {k: v() for k, v in
                 dict_merge(dict.fromkeys(uris, _error_wrapper(E.PkgNotInstalled())),
                            {u: (lambda p=p: remove(p))
                             for u, p in ((u, self.get(*u)) for u in uris) if p}
                            ).items()}
        return coros


_tick_interval = .1


async def init_cli_web_client(*, manager: CliManager) -> aiohttp.ClientSession:
    "A web client that interfaces with the manager's progress bar."
    from cgi import parse_header
    from aiohttp import TraceConfig

    def extract_filename(params: aiohttp.TraceRequestEndParams) -> str:
        cd = params.response.headers.get('Content-Disposition', '')
        _, cd_params = parse_header(cd)
        filename = cd_params.get('filename') or params.response.url.name
        return filename

    async def do_on_request_end(_session, ctx: SimpleNamespace,
                                params: aiohttp.TraceRequestEndParams) -> None:
        # Requests don't have a context unless they
        # originate from ``download_archive``
        if ctx.trace_request_ctx is None:
            return

        bar = manager.bar(label=f'Downloading {extract_filename(params)}',
                          total=params.response.content_length)

        async def ticker(bar=bar, params=params) -> None:
            while not params.response.content._eof:
                bar.current = params.response.content._cursor
                await asyncio.sleep(_tick_interval)
            bar.progress_bar.counters.remove(bar)

        loop = _loop.get()
        loop.create_task(ticker())

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return await init_web_client(trace_configs=[trace_config])


async def _intercept(coro: Coroutine) -> E.ManagerResult:
    try:
        return await coro
    except E.ManagerError as error:
        return error
    except Exception as error:
        logger.exception('internal error')
        return E.InternalError(error=error)


class CliManager(Manager):

    def __init__(self, config: Config,
                 progress_bar_factory: Optional[Callable] = None) -> None:
        super().__init__(config, partial(init_cli_web_client, manager=self))
        self.progress_bar_factory = progress_bar_factory or make_progress_bar

    @logger.catch(reraise=True)
    def _process(self, prepper: Callable,
                 uris: Sequence[_Uri], *args: Any) -> List[E.ManagerResult]:
        async def do_process():
            coros = await prepper(list(uris), *args)
            return [await _intercept(c) for c in coros.values()]

        with self.bar:
            return self.run(do_process())

    @cached_property
    def bar(self) -> Callable:
        return self.progress_bar_factory()

    @property
    def install(self) -> Callable:
        return partial(self._process, self.prep_install)

    @property
    def update(self) -> Callable:
        return partial(self._process, self.prep_update)

    @property
    def remove(self) -> Callable:
        return partial(self._process, self.prep_remove)


class WsManager(Manager):

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.web_client_factory = _init_web_client

    def finalise(self, config: Config) -> WsManager:
        self.config = config
        self.resolvers = _ResolverDict(self)
        self.db = prepare_db_session(config=self.config)()
        return self

    async def _poll(self, web_request: aiohttp.web.Request) -> None:
        import aiohttp
        from .api import (ErrorCodes, ApiError,
                          Request, InstallRequest, UpdateRequest, RemoveRequest,
                          SuccessResponse, ErrorResponse,
                          jsonify, parse_request)

        TR = TypeVar('TR', bound=Request)

        async def respond(request: TR, awaitable: Awaitable) -> None:
            try:
                result = await awaitable
            except ApiError as error:
                response = ErrorResponse.from_api_error(error)
            except E.ManagerError as error:
                values = {'id': request.id,
                          'error': {'code': ErrorCodes[type(error).__name__],
                                    'message': error.message}}
                response = ErrorResponse(**values)
            except Exception:
                logger.exception('internal error')
                values = {'id': request.id,
                          'error': {'code': ErrorCodes.INTERNAL_ERROR,
                                    'message': 'encountered an internal error'}}
                response = ErrorResponse(**values)
            else:
                response = request.consume_result(result)
            await websocket.send_json(response, dumps=jsonify)

        async def receiver() -> None:
            async for message in websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    try:
                        request = parse_request(message.data)
                    except ApiError as error:
                        async def schedule_error(error=error):
                            raise error
                        _loop.get().create_task(respond(None, schedule_error()))  # type: ignore
                    else:
                        if request.__class__ in {InstallRequest, UpdateRequest, RemoveRequest}:
                            # Here we're wrapping the coroutine in a future
                            # that the consumer will `wait_for` to complete therefore
                            # preserving the order of (would-be) synchronous operations
                            future = _loop.get().create_future()
                            consumer_queue.put_nowait((request, future))

                            async def schedule(request=request, future=future):
                                try:
                                    future.set_result(await request.prepare_response(self))
                                except Exception as error:
                                    future.set_exception(error)
                            _loop.get().create_task(schedule())
                        else:
                            _loop.get().create_task(respond(request,
                                                            request.prepare_response(self)))

        async def consumer() -> None:
            while True:
                request, future = await consumer_queue.get()

                async def consume(request=request, future=future):
                    result = await asyncio.wait_for(future, None)
                    if request.__class__ in {InstallRequest, UpdateRequest}:
                        result = await result()
                    return result
                await respond(request, consume())
                consumer_queue.task_done()

        consumer_queue: asyncio.Queue[Tuple[Request,
                                            asyncio.Future]] = asyncio.Queue()
        websocket = aiohttp.web.WebSocketResponse()

        await websocket.prepare(web_request)
        _loop.get().create_task(consumer())
        await receiver()

    def serve(self, host: str = '127.0.0.1', port: Optional[int] = None) -> None:
        async def aserve():
            import os
            import socket
            from aiohttp import web

            app = web.Application()
            app.router.add_routes([web.get('/', self._poll)])    # type: ignore
            app_runner = web.AppRunner(app)
            await app_runner.setup()

            server = await _loop.get().create_server(app_runner.server, host, port,
                                                     family=socket.AF_INET)
            sock = server.sockets[0]
            message = ('{{"address": "ws://{}:{}/"}}\n'
                       .format(*sock.getsockname()).encode())
            try:
                # Try sending message over fd 3 for IPC with Node
                # and if that fails...
                os.write(3, message)
            except OSError:
                # ... write to stdout
                os.write(1, message)

            try:
                await server.serve_forever()
            except (KeyboardInterrupt, SystemExit):
                pass
            finally:
                await app_runner.cleanup()

        self.run(aserve())
