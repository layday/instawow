
from __future__ import annotations

import asyncio
import contextvars
from functools import partial
import io
from pathlib import Path
from typing import TYPE_CHECKING
from typing import (Any, Awaitable, Callable, Iterable, List,
                    NoReturn, Optional, Tuple, Type)

import logbook
from send2trash import send2trash
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .config import Config
from . import exceptions as E
from .models import ModelBase, Pkg, PkgFolder
from .resolvers import *

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass

if TYPE_CHECKING:
    import aiohttp


__all__ = ('Manager', 'CliManager')


logger = logbook.Logger(__name__)


_UA_STRING = 'instawow (https://github.com/layday/instawow)'

_client = contextvars.ContextVar('_client')


def _init_db_session(*, config: Config):
    engine = create_engine(f'sqlite:///{config.config_dir / "db.sqlite"}')
    ModelBase.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


async def _init_web_client(*, loop: asyncio.AbstractEventLoop,
                           **kwargs) -> aiohttp.ClientSession:
    from aiohttp import ClientSession, TCPConnector
    return ClientSession(loop=loop,
                         connector=TCPConnector(loop=loop, limit_per_host=10),
                         headers={'User-Agent': _UA_STRING},
                         **kwargs)


def trash(paths: Iterable[Path]) -> None:
    for path in paths:
        send2trash(str(path))


class PkgArchive:

    __slots__ = ('archive', 'root_folders')

    def __init__(self, payload: bytes) -> None:
        from zipfile import ZipFile

        self.archive = ZipFile(io.BytesIO(payload))
        self.root_folders = sorted({Path(Path(p).parts[0])
                                    for p in self.archive.namelist()})

    def extract(self, parent_folder: Path, *,
                overwrite: bool=False) -> None:
        "Extract the archive contents under ``parent_folder``."
        if not overwrite:
            conflicts = {f.name for f in self.root_folders} & \
                        {f.name for f in parent_folder.iterdir()}
            if conflicts:
                raise E.PkgConflictsWithPreexisting(conflicts)
        self.archive.extractall(parent_folder)


class MemberDict(dict):

    def __missing__(self, key):
        raise E.PkgOriginInvalid


class Manager:

    def __init__(self, *,
                 config: Config, loop: Optional[asyncio.AbstractEventLoop]=None,
                 client_factory: Optional[Callable]=None) -> None:
        self.config = config
        self.loop = loop or asyncio.get_event_loop()
        self.client_factory = partial(client_factory or _init_web_client,
                                      loop=self.loop)
        self.client = _client
        self.db = _init_db_session(config=self.config)
        self.resolvers = MemberDict((r.origin, r(manager=self))
                                    for r in (CurseResolver, WowiResolver,
                                              TukuiResolver, InstawowResolver))

    async def _download_file(self, url: str) -> bytes:
        if url[:7] == 'file://':
            from urllib.parse import unquote

            file = Path(unquote(url[7:]))
            return await self.loop.run_in_executor(None,
                                                   lambda: file.read_bytes())
        async with self.client.get()\
                              .get(url) as response:
            return await response.read()

    def get(self, origin: str, id_or_slug: str) -> Pkg:
        "Retrieve a ``Pkg`` from the database."
        return self.db.query(Pkg)\
                      .filter(Pkg.origin == origin,
                              (Pkg.id == id_or_slug) | (Pkg.slug == id_or_slug))\
                      .first()

    async def resolve(self, origin: str, id_or_slug: str, strategy: str) -> Pkg:
        "Resolve an ID or slug into a ``Pkg``."
        return await self.resolvers[origin].resolve(id_or_slug,
                                                    strategy=strategy)

    async def to_install(self, origin: str, id_or_slug: str,
                         strategy: str, overwrite: bool) -> Callable[[], E.PkgInstalled]:
        "Retrieve a package to install."
        async def install():
            archive = PkgArchive(payload)
            pkg.folders = [PkgFolder(path=self.config.addon_dir / f)
                           for f in archive.root_folders]

            conflicts = self.db.query(PkgFolder)\
                               .filter(PkgFolder.path.in_([f.path for f in pkg.folders]))\
                               .first()
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts.pkg)

            if overwrite:
                trash_ = partial(trash, (f.path for f in pkg.folders
                                         if f.path.exists()))
                await self.loop.run_in_executor(None, trash_)
            extract = partial(archive.extract, self.config.addon_dir,
                              overwrite=overwrite)
            await self.loop.run_in_executor(None, extract)
            self.db.add(pkg)
            self.db.commit()
            return E.PkgInstalled(pkg)

        if self.get(origin, id_or_slug):
            raise E.PkgAlreadyInstalled
        pkg = await self.resolve(origin, id_or_slug, strategy)

        payload = await self._download_file(pkg.download_url)
        return install

    async def to_update(self, origin: str, id_or_slug: str) -> Callable[[], E.PkgUpdated]:
        "Retrieve a package to update."
        async def update():
            archive = PkgArchive(payload)
            new_pkg.folders = [PkgFolder(path=self.config.addon_dir / f)
                               for f in archive.root_folders]

            conflicts = self.db.query(PkgFolder)\
                               .filter(PkgFolder.path.in_([f.path for f in new_pkg.folders]),
                                       PkgFolder.pkg_origin != new_pkg.origin,
                                       PkgFolder.pkg_id != new_pkg.id)\
                               .first()
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts.pkg)

            try:
                trash_ = partial(trash, (f.path for f in cur_pkg.folders))
                await self.loop.run_in_executor(None, trash_)
                self.db.delete(cur_pkg)
                extract = partial(archive.extract,
                                  parent_folder=self.config.addon_dir)
                await self.loop.run_in_executor(None, extract)
                self.db.add(new_pkg)
            finally:
                self.db.commit()
            return E.PkgUpdated(cur_pkg, new_pkg)

        cur_pkg = self.get(origin, id_or_slug)
        if not cur_pkg:
            raise E.PkgNotInstalled
        new_pkg = await self.resolve(origin, id_or_slug, cur_pkg.options.strategy)
        if cur_pkg.file_id == new_pkg.file_id:
            raise E.PkgUpToDate

        payload = await self._download_file(new_pkg.download_url)
        return update

    async def remove(self, origin: str, id_or_slug: str) -> E.PkgRemoved:
        "Remove a package."
        pkg = self.get(origin, id_or_slug)
        if not pkg:
            raise E.PkgNotInstalled

        trash_ = partial(trash, (f.path for f in pkg.folders))
        await self.loop.run_in_executor(None, trash_)
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


async def _init_cli_web_client(*, loop: asyncio.AbstractEventLoop,
                               manager: CliManager) -> aiohttp.ClientSession:
    from aiohttp import TraceConfig

    async def do_on_request_end(_session, _ctx,
                                params: aiohttp.TraceRequestEndParams) -> None:
        if params.response.content_type in {
                'application/zip',
                # Curse at it again
                'application/x-amz-json-1.0'}:
            filename = params.response.headers.get('Content-Disposition', '')
            filename = filename[(filename.find('"') + 1):filename.rfind('"')] or \
                       params.response.url.name
            bar = manager.Bar(total=params.response.content_length,
                              desc=f'  Downloading {filename}',
                              miniters=1, unit='B', unit_scale=True,
                              position=manager.bar_position)

            async def ticker(bar=bar, params=params) -> None:
                while not params.response.content._eof:
                    bar.update(params.response.content._cursor - bar.n)
                    await asyncio.sleep(bar.mininterval)
                bar.close()
            loop.create_task(ticker())

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return await _init_web_client(loop=loop, trace_configs=[trace_config])


class SafeFuture(asyncio.Future):

    def result(self) -> Any:
        return self.exception() or super().result()

    async def intercept(self, awaitable: Awaitable) -> SafeFuture:
        try:
            self.set_result(await awaitable)
        except E.ManagerError as error:
            self.set_exception(error)
        except Exception as error:
            logger.exception()
            self.set_exception(E.InternalError(error=error))
        return self


class CliManager(Manager):

    def __init__(self, *,
                 config: Config, loop: Optional[asyncio.AbstractEventLoop]=None,
                 show_progress: bool=True) -> None:
        super().__init__(config=config, loop=loop,
                         client_factory=(partial(_init_cli_web_client, manager=self)
                                         if show_progress else None))
        self.show_progress = show_progress
        self.bar_positions = [False]

        from tqdm import tqdm
        self.Bar = type('Bar', (Bar, tqdm), {})

    @property
    def bar_position(self) -> Tuple[int, Callable]:
        "Get the first available bar slot."
        try:
            b = self.bar_positions.index(False)
            self.bar_positions[b] = True
        except ValueError:
            b = len(self.bar_positions)
            self.bar_positions.append(True)
        return (b, lambda b=b: self.bar_positions.__setitem__(b, False))

    def run(self, awaitable: Awaitable) -> Any:
        "Run ``awaitable`` inside an explicit context."
        async def runner():
            async with (await self.client_factory()) as client:
                _client.set(client)
                return await awaitable

        return contextvars.copy_context().run(partial(self.loop.run_until_complete,
                                                      runner()))

    async def gather(self, it: Iterable, *, desc=None) -> List[SafeFuture]:
        async def intercept(coro, index, bar):
            future = await SafeFuture(loop=self.loop).intercept(coro)
            bar.update(1)
            return index, future

        coros = list(it)
        with self.Bar(total=len(coros), disable=not self.show_progress,
                      position=self.bar_position, desc=desc) as bar:
            futures = [intercept(c, i, bar) for i, c in enumerate(coros)]
            results = [v for _, v in
                       sorted([await r for r in
                               asyncio.as_completed(futures, loop=self.loop)])]

            # Wait for ``ticker``s to complete so all bars get to wipe
            # their pretty faces off the face of the screen
            while len(asyncio.all_tasks(self.loop)) > 1:
                await asyncio.sleep(bar.mininterval)
        return results

    def resolve_many(self, values: Iterable) -> List[E.ManagerResult]:
        async def resolve_many():
            return [r.result() for r in
                    (await self.gather((self.resolve(*a) for a in values),
                                       desc='Resolving'))]

        return self.run(resolve_many())

    def install_many(self, values: Iterable) -> List[E.ManagerResult]:
        async def install_many():
            return [(r if r.exception() else
                     await SafeFuture(loop=self.loop).intercept(r.result()())
                     ).result()
                    for r in (await self.gather((self.to_install(*a) for a in values),
                                                desc='Fetching'))]

        return self.run(install_many())

    def update_many(self, values: Iterable) -> List[E.ManagerResult]:
        async def update_many():
            return [(r if r.exception() else
                     await SafeFuture(loop=self.loop).intercept(r.result()())
                     ).result()
                    for r in (await self.gather((self.to_update(*a) for a in values),
                                                desc='Checking'))]

        return self.run(update_many())


class WsManager(Manager):

    async def poll(self, web_request: aiohttp.web.Request) -> None:
        import aiohttp
        from .api import (ApiError, ErrorCodes, parse_request, jsonify,
                          Request, InstallRequest, UpdateRequest, RemoveRequest,
                          SuccessResponse, ErrorResponse)

        async def respond(request: Request, awaitable: Awaitable) -> None:
            try:
                result = await awaitable
            except ApiError as error:
                response = ErrorResponse.from_api_error(error)
            except E.ManagerError as error:
                response = ErrorResponse(**{'id': request.id,
                                            'error': {'code': ErrorCodes[type(error).__name__],
                                                      'message': error.message}})
            except Exception:
                logger.exception()
                response = ErrorResponse(**{'id': request.id,
                                            'error': {'code': ErrorCodes.INTERNAL_ERROR,
                                                      'message': 'encountered internal error'}})
            else:
                response = request.consume_result(result)

            await websocket.send_json(response, dumps=jsonify)

        async def receiver() -> None:
            async for message in websocket:
                if message.type == aiohttp.WSMsgType.TEXT:
                    try:
                        request = parse_request(message.data)
                    except ApiError as error:
                        async def schedule_error(error=error) -> NoReturn:
                            raise error
                        self.loop.create_task(respond(None, schedule_error()))  # type: ignore
                    else:
                        if request.__class__ in {InstallRequest, UpdateRequest, RemoveRequest}:
                            # Here we're wrapping the coroutine in a future
                            # that the consumer will `wait_for` to complete therefore
                            # preserving the order of (would-be) synchronous operations
                            future = self.loop.create_future()
                            consumer_queue.put_nowait((request, future))

                            async def schedule(request=request, future=future) -> None:
                                try:
                                    future.set_result(await request.prepare_response(self))
                                except Exception as error:
                                    future.set_exception(error)
                            self.loop.create_task(schedule())
                        else:
                            self.loop.create_task(respond(request,
                                                          request.prepare_response(self)))

        async def consumer() -> None:
            while True:
                request, future = await consumer_queue.get()

                async def consume(request=request, future=future) -> Any:
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
        self.loop.create_task(consumer())

        async with (await self.client_factory()) as client:
            _client.set(client)
            await receiver()

    def serve(self, host: Optional[str]=None, port: Optional[int]=None) -> None:
        def runner() -> None:
            from aiohttp import web

            app_runner = None

            async def build():
                nonlocal app_runner

                app = web.Application()
                app.router.add_routes([web.get('/', self.poll)])    # type: ignore
                app_runner = web.AppRunner(app)
                await app_runner.setup()
                site = web.TCPSite(app_runner, host, port)
                await site.start()

            async def destroy():
                await app_runner.cleanup()

            self.loop.run_until_complete(build())
            try:
                self.loop.run_forever()
            except (KeyboardInterrupt, web.GracefulExit):
                pass
            finally:
                self.loop.run_until_complete(destroy())

        contextvars.copy_context().run(runner)
