
import asyncio
from contextlib import ExitStack
import contextvars
from functools import partial
import io
from pathlib import Path
import typing as T
from zipfile import ZipFile

from aiohttp import ClientSession, TCPConnector, TraceConfig
import logbook
from send2trash import send2trash
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tqdm import tqdm

from .config import Config
from . import exceptions as E
from .models import ModelBase, Pkg, PkgFolder
from .resolvers import CurseResolver, WowiResolver, TukuiResolver


__all__ = ('Manager', 'CliManager')


logger = logbook.Logger(__name__)


_UA_STRING = 'instawow (https://github.com/layday/instawow)'

_client = contextvars.ContextVar('_client')


def _init_loop():
    try:
        import uvloop
    except ImportError:
        return asyncio.get_event_loop()
    else:
        return uvloop.new_event_loop()


def _init_db_session(*, config):
    engine = create_engine(f'sqlite:///{config.config_dir/"db.sqlite"}')
    ModelBase.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


async def _init_web_client(*, loop, **kwargs):
    return ClientSession(loop=loop,
                         connector=TCPConnector(loop=loop, limit_per_host=10),
                         headers={'User-Agent': _UA_STRING},
                         **kwargs)


class PkgArchive:

    __slots__ = ('archive', 'root_folders')

    def __init__(self, payload: bytes) -> None:
        self.archive = ZipFile(io.BytesIO(payload))

        folders = sorted({Path(p).parts[0] for p in self.archive.namelist()})
        self.root_folders = [Path(p) for p in folders]

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
        raise E.PkgOriginInvalid(origin=key)


class Manager:

    def __init__(self, *,
                 config: Config, loop: asyncio.AbstractEventLoop=None,
                 client_factory: T.Callable=None) -> None:
        self.config = config
        self.loop = loop or _init_loop()
        self.client_factory = partial(client_factory or _init_web_client,
                                      loop=self.loop)
        self.client = _client
        self.db = _init_db_session(config=self.config)
        self.resolvers = MemberDict((r.origin, r(manager=self))
                                    for r in (CurseResolver, WowiResolver, TukuiResolver))

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

    async def to_install(self, origin: str, id_or_slug: str, strategy: str,
                         overwrite: bool) -> T.Callable[[], E.PkgInstalled]:
        "Retrieve a package to install."
        def install():
            archive = PkgArchive(payload)
            pkg.folders = [PkgFolder(path=self.config.addon_dir/f)
                           for f in archive.root_folders]

            conflicts = self.db.query(PkgFolder)\
                               .filter(PkgFolder.path.in_
                                        ([f.path for f in pkg.folders]))\
                               .first()
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts.pkg)

            if overwrite:
                for path in (f.path for f in pkg.folders if f.path.exists()):
                    send2trash(str(path))
            archive.extract(parent_folder=self.config.addon_dir,
                            overwrite=overwrite)
            self.db.add(pkg)
            self.db.commit()
            return E.PkgInstalled(pkg)

        if self.get(origin, id_or_slug):
            raise E.PkgAlreadyInstalled
        pkg = await self.resolve(origin, id_or_slug, strategy)
        async with self.client.get()\
                              .get(pkg.download_url) as response:
            payload = await response.read()
        return install

    async def to_update(self, origin: str,
                        id_or_slug: str) -> T.Callable[[], E.PkgUpdated]:
        "Retrieve a package to update."
        def update():
            archive = PkgArchive(payload)
            new_pkg.folders = [PkgFolder(path=self.config.addon_dir/f)
                               for f in archive.root_folders]

            conflicts = self.db.query(PkgFolder)\
                               .filter(PkgFolder.path.in_
                                        ([f.path for f in new_pkg.folders]),
                                       PkgFolder.pkg_origin != new_pkg.origin,
                                       PkgFolder.pkg_id != new_pkg.id)\
                               .first()
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts.pkg)

            with ExitStack() as stack:
                stack.callback(self.db.commit)
                for folder in old_pkg.folders:
                    send2trash(str(folder.path))
                self.db.delete(old_pkg)
                archive.extract(parent_folder=self.config.addon_dir)
                self.db.add(new_pkg)
            return E.PkgUpdated(old_pkg, new_pkg)

        old_pkg = self.get(origin, id_or_slug)
        if not old_pkg:
            raise E.PkgNotInstalled
        new_pkg = await self.resolve(origin, id_or_slug, old_pkg.options.strategy)
        if old_pkg.file_id == new_pkg.file_id:
            raise E.PkgUpToDate

        async with self.client.get()\
                              .get(new_pkg.download_url) as response:
            payload = await response.read()
        return update

    def remove(self, origin: str, id_or_slug: str) -> E.PkgRemoved:
        "Remove a package."
        pkg = self.get(origin, id_or_slug)
        if not pkg:
            raise E.PkgNotInstalled

        for folder in pkg.folders:
            send2trash(str(folder.path))
        self.db.delete(pkg)
        self.db.commit()
        return E.PkgRemoved(pkg)


class Bar(tqdm):

    def __init__(self, *args, **kwargs) -> None:
        kwargs['position'], self.__reset_position = kwargs['position']
        super().__init__(*args, **{'leave': False, 'ascii': True, **kwargs})

    def close(self) -> None:
        super().close()
        self.__reset_position()


async def _init_cli_web_client(*, loop, manager):
    async def do_on_request_end(session, context, params):
        if params.response.content_type in {
                'application/zip',
                # Curse at it again
                'application/x-amz-json-1.0'}:
            filename = params.response.headers.get('Content-Disposition', '')
            filename = filename[(filename.find('"') + 1):filename.rfind('"')] or \
                       params.response.url.name
            bar = Bar(total=params.response.content_length,
                      desc=f'  Downloading {filename}',
                      miniters=1, unit='B', unit_scale=True,
                      position=manager.bar_position)

            async def ticker(bar=bar, params=params):
                while not params.response.content._eof:
                    bar.update(params.response.content._cursor - bar.n)
                    await asyncio.sleep(bar.mininterval)
                bar.close()
            loop.create_task(ticker())

    trace_conf = TraceConfig()
    trace_conf.on_request_end.append(do_on_request_end)
    trace_conf.freeze()
    return await _init_web_client(loop=loop, trace_configs=[trace_conf])


class CliManager(Manager):

    def __init__(self, *,
                 config: Config, loop: asyncio.AbstractEventLoop=None,
                 show_progress: bool=True) -> None:
        super().__init__(config=config, loop=loop,
                         client_factory=(partial(_init_cli_web_client, manager=self)
                                         if show_progress else None))
        self.show_progress = show_progress
        self._bar_position = []

    @property
    def bar_position(self) -> T.Tuple[int, T.Callable]:
        "Get the first available bar slot."
        try:
            b = self._bar_position.index(False)
            self._bar_position[b] = True
        except ValueError:
            b = len(self._bar_position)
            self._bar_position.append(True)
        return (b, lambda b=b: self._bar_position.__setitem__(b, False))

    def run(self, awaitable: T.Awaitable) -> T.Any:
        "Run ``awaitable`` inside an explicit context."
        async def runner():
            async with (await self.client_factory()) as client:
                _client.set(client)
                return await awaitable

        return contextvars.copy_context().run(partial(self.loop.run_until_complete,
                                                      runner()))

    async def gather(self, it: T.Iterable, **kwargs) -> list:
        async def intercept_exc(position, awaitable):
            try:
                result = await awaitable
            except E.ManagerError as error:
                result = error
            except Exception as error:
                logger.exception()
                result = E.InternalError(error=error)
            return position, result

        futures = [intercept_exc(*i) for i in enumerate(it)]
        results = [None] * len(futures)
        with Bar(total=len(futures), disable=not self.show_progress,
                 position=self.bar_position, **kwargs) as bar:
            for result in asyncio.as_completed(futures, loop=self.loop):
                results.__setitem__(*await result)
                bar.update(1)
            # Wait for ``ticker``s to complete so all bars get to wipe
            # their pretty selves off the screen
            while len(asyncio.all_tasks(self.loop)) > 1:
                await asyncio.sleep(bar.mininterval)
        return results

    @staticmethod
    def _intercept_exc(callable_):
        try:
            result = callable_()
        except E.ManagerError as error:
            result = error
        except Exception as error:
            logger.exception()
            result = E.InternalError(error=error)
        return result

    def resolve_many(self, values: T.Iterable) -> list:
        results = self.run(self.gather((self.resolve(*a) for a in values),
                                       desc='Resolving'))
        return results

    def install_many(self, values: T.Iterable) -> list:
        results = self.run(self.gather((self.to_install(*a) for a in values),
                                       desc='Fetching'))
        return [self._intercept_exc(i) for i in results]

    def update_many(self,  values: T.Iterable) -> list:
        results = self.run(self.gather((self.to_update(*a) for a in values),
                                       desc='Checking'))
        return [self._intercept_exc(i) for i in results]
