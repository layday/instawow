
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import shutil
import typing

from aiohttp import ClientSession, TCPConnector
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvloop

from .config import Config
from .models import ModelBase, Pkg, PkgFolder
from .resolvers import BaseResolver
from .utils import Archive, ProgressBar


def _dedupe(it):
    list_ = list(it)
    return sorted(set(list_), key=list_.index)


async def _intercept_coro(index, future):
    try:
        result = await future
    except Exception as e:
        result = e
    return index, result


class ManagerException(Exception):
    pass


class PkgAlreadyInstalled(ManagerException):
    pass


class PkgConflictsWithInstalled(ManagerException):

    def __init__(self, conflicting_pkg):
        super().__init__()
        self.conflicting_pkg = conflicting_pkg


class PkgConflictsWithPreexisting(ManagerException):
    pass


class PkgNonexistent(ManagerException):
    pass


class PkgNotInstalled(ManagerException):
    pass


class PkgOriginInvalid(ManagerException):
    pass


class PkgUpToDate(ManagerException):
    pass


class _AsyncUtilsMixin:

    def __init__(self,
                 *,
                 loop):
        self._loop = loop

    async def block_in_thread(self, *args,
                              _tpe=ThreadPoolExecutor(max_workers=1)):
        return await self._loop.run_in_executor(_tpe, *args)

    def run(self, *args, **kwargs):
        return self._loop.run_until_complete(*args, **kwargs)

    async def gather(self, it, *,
                     show_progress: bool=False) -> typing.List[typing.Any]:
        """Execute coroutines concurrently and gather their results, including
        exceptions.  This displays a progress bar in the command line if
        `show_process=True`.
        """
        if not show_progress:
            return await asyncio.gather(*it, loop=self._loop)

        futures = [_intercept_coro(i, f) for i, f in enumerate(it)]
        results = [None] * len(futures)
        with ProgressBar(length=len(futures)) as bar:
            for result in asyncio.as_completed(futures, loop=self._loop):
                results.__setitem__(*(await result))
                bar.update(1)
        return results


class Manager(_AsyncUtilsMixin):

    ManagerException = ManagerException
    PkgAlreadyInstalled = PkgAlreadyInstalled
    PkgConflictsWithPreexisting = PkgConflictsWithPreexisting
    PkgConflictsWithInstalled = PkgConflictsWithInstalled
    PkgNonexistent = PkgNonexistent
    PkgNotInstalled = PkgNotInstalled
    PkgOriginInvalid = PkgOriginInvalid
    PkgUpToDate = PkgUpToDate

    def __init__(self,
                 *,
                 config: Config,
                 loop: asyncio.BaseEventLoop=uvloop.new_event_loop(),
                 show_progress: bool=True):
        super().__init__(loop=loop)
        self.config = config
        self.show_progress = show_progress

        db_engine = create_engine(f'sqlite:///{config.config_dir/config.db_name}')
        ModelBase.metadata.create_all(db_engine)
        self.db = sessionmaker(bind=db_engine)()

        self.client = \
            ClientSession(connector=TCPConnector(limit_per_host=10, loop=loop),
                          loop=loop)
        self.resolvers = {n: r(manager=self)
                          for n, r in BaseResolver.__members__.items()}

        self._prepare_lock = asyncio.Lock(loop=loop)
        self._install_lock = asyncio.Lock(loop=loop)

    async def _prepare_resolver(self, origin):
        resolver = self.resolvers[origin]
        async with self._prepare_lock:
            if not resolver.synced:
                await resolver._sync()
        return resolver

    def close(self):
        self.client.close()

    async def resolve(self, origin, id_or_slug, strategy):
        if origin not in self.resolvers:
            raise PkgOriginInvalid
        return await (await self._prepare_resolver(origin))\
            .resolve(id_or_slug, strategy=strategy)

    async def resolve_many(self,
                           triplets: typing.Iterable) -> typing.List[Pkg]:
        return await self.gather((self.resolve(*t) for t in _dedupe(triplets)),
                                 show_progress=self.show_progress)

    async def install(self, origin, id_or_slug, strategy, overwrite):
        if Pkg.unique(origin, id_or_slug, self.db):
            raise PkgAlreadyInstalled

        new_pkg = await self.resolve(origin, id_or_slug, strategy)
        async with self.client.get(new_pkg.download_url) as resp:
            payload = await resp.read()

        async with self._install_lock:
            folder_conflict = self.db\
                .query(PkgFolder)\
                .filter(PkgFolder.path.in_([f.path for f in new_pkg.folders]))\
                .first()
            if folder_conflict:
                raise PkgConflictsWithInstalled(folder_conflict.pkg)
            try:
                await self.block_in_thread(partial(Archive(payload).extract,
                                                   self.config.addon_dir,
                                                   overwrite=overwrite))
            except Archive.ExtractConflict:
                raise PkgConflictsWithPreexisting
            else:
                return new_pkg.insert(self.db)

    async def install_many(self,
                           quadruplets: typing.Iterable) -> typing.List[Pkg]:
        return await self.gather((self.install(*q) for q in _dedupe(quadruplets)),
                                 show_progress=self.show_progress)

    async def update(self, origin, id_or_slug):
        old_pkg = Pkg.unique(origin, id_or_slug, self.db)
        if not old_pkg:
            raise PkgNotInstalled

        new_pkg = await self.resolve(origin, id_or_slug, old_pkg.options.strategy)
        if old_pkg.file_id == new_pkg.file_id:
            raise PkgUpToDate

        async with self.client.get(new_pkg.download_url) as resp:
            payload = await resp.read()

        async with self._install_lock:
            folder_conflict = self.db\
                .query(PkgFolder)\
                .filter(PkgFolder.path.in_([f.path for f in new_pkg.folders]),
                        PkgFolder.pkg_origin != new_pkg.origin,
                        PkgFolder.pkg_id != new_pkg.id)\
                .first()
            if folder_conflict:
                raise PkgConflictsWithInstalled(folder_conflict.pkg)

            await self.block_in_thread(partial(Archive(payload).extract,
                                               self.config.addon_dir,
                                               overwrite=True))
            return old_pkg, new_pkg.replace(old_pkg, self.db)

    async def update_many(self,
                          pairs: typing.Iterable) -> typing.List[typing.Tuple[Pkg, Pkg]]:
        return await self.gather((self.update(*p) for p in _dedupe(pairs)),
                                 show_progress=self.show_progress)

    def remove(self, origin, id_or_slug):
        pkg = Pkg.unique(origin, id_or_slug, self.db)
        if not pkg:
            raise PkgNotInstalled

        for folder in pkg.folders:
            shutil.rmtree(folder.path)
        pkg.delete(self.db)
