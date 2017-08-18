
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, closing
import shutil

from aiohttp import ClientSession, TCPConnector
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import uvloop

from .models import ModelBase, Pkg, PkgFolder
from .resolvers import BaseResolver
from .utils import Archive


class PkgAlreadyInstalled(Exception):
    pass


class PkgConflictsWithInstalled(Exception):

    def __init__(self, conflicting_pkg):
        super().__init__()
        self.conflicting_pkg = conflicting_pkg


class PkgConflictsWithPreexisting(Exception):
    pass


class PkgNonexistent(Exception):
    pass


class PkgNotInstalled(Exception):
    pass


class PkgOriginInvalid(Exception):
    pass


class PkgUpToDate(Exception):
    pass


async def _prepare_resolver(manager, resolver):
    r = resolver(manager=manager)
    await r.sync()
    r.load()
    return r


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

    PkgAlreadyInstalled = PkgAlreadyInstalled
    PkgConflictsWithPreexisting = PkgConflictsWithPreexisting
    PkgConflictsWithInstalled = PkgConflictsWithInstalled
    PkgNonexistent = PkgNonexistent
    PkgNotInstalled = PkgNotInstalled
    PkgOriginInvalid = PkgOriginInvalid
    PkgUpToDate = PkgUpToDate

    def __init__(self,
                 *,
                 loop,
                 config,
                 debug=False):
        super().__init__(loop=loop)
        self.config = config

        self._resolve_lock = asyncio.Lock(loop=loop)
        self._synced_resolvers = False
        self.resolvers = BaseResolver.__members__

        _engine = create_engine(f'''sqlite:///{self.config.config_dir/
                                               self.config.db_name}''',
                                echo=debug)
        ModelBase.metadata.create_all(_engine)
        self.db = sessionmaker(bind=_engine)()

        self.client = \
            ClientSession(connector=TCPConnector(limit_per_host=10, loop=loop),
                          loop=loop)

    async def _prepare_resolvers(self):
        async with self._resolve_lock:
            if not self._synced_resolvers:
                self.resolvers = {n: await _prepare_resolver(self, r)
                                  for n, r in self.resolvers.items()}
                self._synced_resolvers = True

    def close(self):
        self.client.close()

    async def resolve(self, origin, id_or_slug, strategy):
        if origin not in self.resolvers:
            raise PkgOriginInvalid
        await self._prepare_resolvers()
        return await self.resolvers[origin].resolve(id_or_slug, strategy=strategy)

    async def resolve_many(self, triplets):
        return await self.gather((self.resolve(*t) for t in triplets),
                                 return_exceptions=True)

    async def install(self, origin, id_or_slug, strategy, overwrite):
        if Pkg.unique(origin, id_or_slug, self.db):
            raise PkgAlreadyInstalled
        new_pkg = await self.resolve(origin, id_or_slug, strategy)

        conflicts = {f.path for f in new_pkg.folders} & \
                    {f.path for f in self.db.query(PkgFolder).all()}
        conflicts = list(conflicts)
        if conflicts:
            raise PkgConflictsWithInstalled(self.db.query(PkgFolder)
                                                .filter(PkgFolder.path.in_(conflicts))
                                                .first().pkg)

        async with self.client.get(new_pkg.download_url) as resp:
            payload = await resp.read()
        try:
            await self.block_in_thread(lambda: Archive(payload).extract(self.config.addon_dir,
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
        conflicts = list(conflicts)
        if conflicts:
            raise PkgConflictsWithInstalled(self.db.query(PkgFolder)
                                                .filter(PkgFolder.path.in_(conflicts))
                                                .first().pkg)

        async with self.client.get(new_pkg.download_url) as resp:
            payload = await resp.read()
        await self.block_in_thread(lambda: Archive(payload).extract(self.config.addon_dir,
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


@contextmanager
def run(config, loop=uvloop.new_event_loop()):
    with closing(Manager(loop=loop, config=config)) as manager:
        yield manager
