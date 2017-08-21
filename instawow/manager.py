
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import shutil

from aiohttp import ClientSession, TCPConnector
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvloop

from .models import ModelBase, Pkg, PkgFolder
from .resolvers import BaseResolver
from .utils import Archive


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

    async def gather(self, iterable, **kwargs):
        return await asyncio.gather(*iterable,
                                    loop=self._loop,
                                    **kwargs)

    def run(self, *args, **kwargs):
        return self._loop.run_until_complete(*args, **kwargs)


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
                 config,
                 loop=uvloop.new_event_loop()):
        super().__init__(loop=loop)
        self.config = config

        db_engine = create_engine(f'sqlite:///{config.config_dir/config.db_name}')
        ModelBase.metadata.create_all(db_engine)
        self.db = sessionmaker(bind=db_engine)()

        self.client = \
            ClientSession(connector=TCPConnector(limit_per_host=10, loop=loop),
                          loop=loop)

        self._prepare_lock = asyncio.Lock(loop=loop)
        self.resolvers = {n: r(manager=self)
                          for n, r in BaseResolver.__members__.items()}

    async def _prepare_resolver(self, origin):
        resolver = self.resolvers[origin]
        async with self._prepare_lock:
            if not resolver.synced:
                await resolver.sync()
                resolver.load()
                resolver.synced = True
        return resolver

    def close(self):
        self.client.close()

    async def resolve(self, origin, id_or_slug, strategy):
        if origin not in self.resolvers:
            raise PkgOriginInvalid
        return await (await self._prepare_resolver(origin))\
            .resolve(id_or_slug, strategy=strategy)

    async def resolve_many(self, triplets):
        return await self.gather((self.resolve(*t) for t in triplets),
                                 return_exceptions=True)

    async def install(self, origin, id_or_slug, strategy, overwrite):
        if Pkg.unique(origin, id_or_slug, self.db):
            raise PkgAlreadyInstalled
        new_pkg = await self.resolve(origin, id_or_slug, strategy)

        conflicts = {f.path for f in new_pkg.folders} & \
                    {f.path for f in self.db.query(PkgFolder).all()}
        if conflicts:
            conflicts = list(conflicts)
            raise PkgConflictsWithInstalled(self.db.query(PkgFolder)
                                                .filter(PkgFolder.path.in_(conflicts))
                                                .first().pkg)

        async with self.client.get(new_pkg.download_url) as resp:
            payload = await resp.read()
        try:
            await self.block_in_thread(partial(Archive(payload).extract,
                                               self.config.addon_dir,
                                               overwrite=overwrite))
        except Archive.ExtractConflict:
            raise PkgConflictsWithPreexisting
        else:
            return new_pkg.insert(self.db)

    async def install_many(self, quadruplets):
        return await self.gather((self.install(*q) for q in quadruplets),
                                 return_exceptions=True)

    async def update(self, origin, id_or_slug):
        old_pkg = Pkg.unique(origin, id_or_slug, self.db)
        if not old_pkg:
            raise PkgNotInstalled
        new_pkg = await self.resolve(origin, id_or_slug, old_pkg.options.strategy)
        if old_pkg.file_id == new_pkg.file_id:
            raise PkgUpToDate

        conflicts = {f.path for f in new_pkg.folders} & \
                    {f.path for f in self.db.query(PkgFolder)
                                         .filter(Pkg.origin != old_pkg.origin,
                                                 Pkg.id != old_pkg.id)
                                         .all()}
        if conflicts:
            conflicts = list(conflicts)
            raise PkgConflictsWithInstalled(self.db.query(PkgFolder)
                                                .filter(PkgFolder.path.in_(conflicts))
                                                .first().pkg)

        async with self.client.get(new_pkg.download_url) as resp:
            payload = await resp.read()
        await self.block_in_thread(partial(Archive(payload).extract,
                                           self.config.addon_dir,
                                           overwrite=True))
        return old_pkg, new_pkg.replace(old_pkg, self.db)

    async def update_many(self, pairs):
        return await self.gather((self.update(*p) for p in pairs),
                                 return_exceptions=True)

    def remove(self, origin, id_or_slug):
        pkg = Pkg.unique(origin, id_or_slug, self.db)
        if not pkg:
            raise PkgNotInstalled

        for folder in pkg.folders:
            shutil.rmtree(folder.path)
        pkg.delete(self.db)
