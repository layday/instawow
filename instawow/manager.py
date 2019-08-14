
from __future__ import annotations

__all__ = ('Manager', 'CliManager', 'WsManager')

import asyncio
from contextlib import asynccontextmanager
import contextvars as cv
from functools import partial
from pathlib import Path, PurePath
from shutil import move as _move
from tempfile import NamedTemporaryFile, mkdtemp
from typing import *
from zipfile import ZipFile

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from . import __db_version__
from .config import Config
from . import exceptions as E
from .models import ModelBase, Pkg, PkgFolder, should_migrate
from .resolvers import (Pkg_,
                        CurseResolver, ClassicCurseResolver, WowiResolver,
                        TukuiResolver, InstawowResolver)

if TYPE_CHECKING:
    import aiohttp


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


@asynccontextmanager
async def new_temp_dir(delete: bool = False) -> AsyncGenerator[PurePath, None]:
    yield PurePath(await async_mkdtemp())


async def move(paths: Iterable[Path], dest: PurePath) -> None:
    for path in paths:
        logger.debug(f'moving {path} to {dest / path.name}')
        await async_move(str(path), str(dest))


class _Archive:

    def __init__(self, archive: ZipFile, delete_after: bool = False):
        self.archive = archive
        self.delete_after = delete_after
        self.folders = {PurePath(p).parts[0] for p in self.archive.namelist()}

    async def extract(self, parent_folder: Path) -> None:
        def extract() -> None:
            conflicts = self.folders & {f.name for f in parent_folder.iterdir()}
            if conflicts:
                raise E.PkgConflictsWithUncontrolled(conflicts)

            self.archive.extractall(parent_folder)
            self.archive.close()
            if self.delete_after:
                Path(self.archive.filename).unlink()

        return await run_in_thread(extract)()


async def download_archive(url: str, *, chunk_size: int = 4096) -> _Archive:
    if url.startswith('file://'):
        from urllib.parse import unquote

        path = Path(unquote(url[7:]))
        return _Archive(await AsyncZipFile(path))
    else:
        async with _web_client.get().get(url) as response, \
                   open_temp_writer() as (path, write):
            async for chunk in response.content.iter_chunked(chunk_size):
                await write(chunk)

        return _Archive(await AsyncZipFile(path), delete_after=True)


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


async def _init_web_client(**kwargs: Any) -> aiohttp.ClientSession:
    from aiohttp import ClientSession, TCPConnector

    kwargs = {'connector': TCPConnector(limit_per_host=10),
              'headers': {'User-Agent': _UA_STRING},
              'trust_env': True,
              **kwargs}
    return ClientSession(**kwargs)


class _ResolverDict(dict):

    def __init__(self, manager: Manager, resolvers: Set[Any]) -> None:
        super().__init__((r.origin, r(manager=manager)) for r in resolvers)

    def __missing__(self, key: Hashable) -> NoReturn:
        raise E.PkgOriginInvalid


class Manager:

    RESOLVERS = {CurseResolver, ClassicCurseResolver, WowiResolver,
                 TukuiResolver, InstawowResolver}

    def __init__(self, config: Config,
                 web_client_factory: Optional[Callable] = None) -> None:
        self.web_client_factory = web_client_factory or _init_web_client
        self.resolvers = _ResolverDict(self, self.RESOLVERS)

        self.config = config
        Session = prepare_db_session(config=self.config)
        self.db = Session()

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

    async def resolve(self, origin: str, id_or_slug: str, strategy: str) -> Pkg_:
        "Resolve an ID or slug into a ``Pkg``."
        return await self.resolvers[origin].resolve(id_or_slug, strategy=strategy)

    async def to_install(self, origin: str, id_or_slug: str,
                         strategy: str, replace: bool) -> Callable:
        "Retrieve a package to install."
        async def install() -> E.PkgInstalled:
            pkg = pkg_(folders=[PkgFolder(name=f) for f in sorted(archive.folders)])
            conflicts = (self.db.query(PkgFolder)
                         .filter(PkgFolder.name.in_([f.name for f in pkg.folders]))
                         .first())
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts.pkg)

            if replace:
                async with new_temp_dir() as dir_name:
                    await move((self.config.addon_dir / f.name
                                for f in pkg.folders), dir_name)

            await archive.extract(self.config.addon_dir)
            self.db.add(pkg)
            self.db.commit()
            return E.PkgInstalled(pkg)

        if self.get(origin, id_or_slug):
            raise E.PkgAlreadyInstalled
        pkg_ = await self.resolve(origin, id_or_slug, strategy)

        archive = await download_archive(pkg_.download_url)
        return install

    async def to_update(self, origin: str, id_or_slug: str) -> Callable:
        "Retrieve a package to update."
        async def update() -> E.PkgUpdated:
            new_pkg = new_pkg_(folders=[PkgFolder(name=f)
                                        for f in sorted(archive.folders)])
            conflicts = (self.db.query(PkgFolder)
                         .filter(PkgFolder.name.in_([f.name for f in new_pkg.folders]),
                                 PkgFolder.pkg_origin != new_pkg.origin,
                                 PkgFolder.pkg_id != new_pkg.id)
                         .first())
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts.pkg)

            async with new_temp_dir() as dir_name:
                await move((self.config.addon_dir / f.name
                            for f in pkg.folders), dir_name)
            await archive.extract(self.config.addon_dir)

            with self.db.begin_nested():
                self.db.delete(pkg)
                self.db.add(new_pkg)

            return E.PkgUpdated(pkg, new_pkg)

        pkg = self.get(origin, id_or_slug)
        if not pkg:
            raise E.PkgNotInstalled

        new_pkg_ = await self.resolve(origin, id_or_slug, pkg.options.strategy)
        if pkg.file_id == new_pkg_.file_id:
            raise E.PkgUpToDate

        archive = await download_archive(new_pkg_.download_url)
        return update

    async def remove(self, origin: str, id_or_slug: str) -> E.PkgRemoved:
        "Remove a package."
        pkg = self.get(origin, id_or_slug)
        if not pkg:
            raise E.PkgNotInstalled

        async with new_temp_dir() as dir_name:
            await move((self.config.addon_dir / f.name
                        for f in pkg.folders), dir_name)

        self.db.delete(pkg)
        self.db.commit()
        return E.PkgRemoved(pkg)


class Bar:

    def __init__(self, *args, **kwargs) -> None:
        kwargs['position'], self.__reset_position = kwargs['position']
        super().__init__(*args, **{'leave': False, 'ascii': True, **kwargs})    # type: ignore

    def close(self) -> None:
        super().close()     # type: ignore
        self.__reset_position()


async def _init_cli_web_client(*, manager: CliManager) -> aiohttp.ClientSession:
    from cgi import parse_header
    from aiohttp import TraceConfig

    async def do_on_request_end(_session, _ctx, params: aiohttp.TraceRequestEndParams) -> None:
        if params.response.content_type in {
                'application/zip',
                # Curse at it again
                'application/x-amz-json-1.0'}:
            cd = params.response.headers.get('Content-Disposition', '')
            _, cd_params = parse_header(cd)
            filename = cd_params.get('filename') or params.response.url.name

            bar = manager.Bar(total=params.response.content_length,
                              desc=f'  Downloading {filename}',
                              miniters=1, unit='B', unit_scale=True,
                              position=manager._get_bar_position())

            async def ticker(bar=bar, params=params) -> None:
                while not params.response.content._eof:
                    bar.update(params.response.content._cursor - bar.n)
                    await asyncio.sleep(bar.mininterval)
                bar.close()
            _loop.get().create_task(ticker())

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return await _init_web_client(trace_configs=[trace_config])


class SafeFuture(asyncio.Future):

    def result(self) -> object:
        return self.exception() or super().result()

    async def intercept(self, awaitable: Awaitable) -> SafeFuture:
        try:
            self.set_result(await awaitable)
        except E.ManagerError as error:
            self.set_exception(error)
        except Exception as error:
            logger.exception('internal error')
            self.set_exception(E.InternalError(error=error))
        return self


class CliManager(Manager):

    def __init__(self, config: Config, show_progress: bool = True) -> None:
        super().__init__(config=config,
                         web_client_factory=(partial(_init_cli_web_client, manager=self)
                                             if show_progress else None))
        self.show_progress = show_progress
        self._bar_positions = [False]

        from tqdm import tqdm
        self.Bar = type('Bar', (Bar, tqdm), {})

    def _get_bar_position(self) -> Tuple[int, Callable]:
        # Get the first available bar slot
        try:
            b = self._bar_positions.index(False)
            self._bar_positions[b] = True
        except ValueError:
            b = len(self._bar_positions)
            self._bar_positions.append(True)
        return (b, lambda b=b: self._bar_positions.__setitem__(b, False))

    async def gather(self, it: Iterable, *,
                     desc: Optional[str] = None) -> List[SafeFuture]:
        async def intercept(coro, index, bar):
            future = await SafeFuture().intercept(coro)
            bar.update(1)
            return index, future

        coros = list(it)
        with self.Bar(total=len(coros), disable=not self.show_progress,
                      position=self._get_bar_position(), desc=desc) as bar:
            futures = [intercept(c, i, bar) for i, c in enumerate(coros)]
            results = [v for _, v in sorted([await r for r in
                                             asyncio.as_completed(futures)])]

            # Wait for ``ticker``s to complete so all bars get to wipe
            # their pretty faces off the face of the screen
            while len(asyncio.all_tasks()) > 1:
                await asyncio.sleep(bar.mininterval)
        return results

    def resolve_many(self, values: Iterable) -> List[Union[E.ManagerResult, Pkg]]:
        async def resolve_many():
            return [r.result() for r in
                    (await self.gather((self.resolve(*a) for a in values),
                                       desc='Resolving'))]

        return self.run(resolve_many())

    def install_many(self, values: Iterable) -> List[E.ManagerResult]:
        async def install_many():
            return [(r if r.exception() else
                     await SafeFuture().intercept(r.result()())
                     ).result()
                    for r in (await self.gather((self.to_install(*a) for a in values),
                                                desc='Fetching'))]

        return self.run(install_many())

    def update_many(self, values: Iterable) -> List[E.ManagerResult]:
        async def update_many():
            return [(r if r.exception() else
                     await SafeFuture().intercept(r.result()())
                     ).result()
                    for r in (await self.gather((self.to_update(*a) for a in values),
                                                desc='Checking'))]

        return self.run(update_many())


class WsManager(Manager):

    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.web_client_factory = _init_web_client
        self.resolvers = _ResolverDict(self, self.RESOLVERS)

    def finalise(self, config: Config) -> WsManager:
        self.config = config
        Session = prepare_db_session(config=self.config)
        self.db = Session()
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
