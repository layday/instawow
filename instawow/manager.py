
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
import shutil
import typing as T

from aiohttp import ClientSession, TCPConnector
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker
from tqdm import tqdm as _tqdm

from .config import Config
from .models import ModelBase, Pkg, PkgFolder
from .resolvers import BaseResolver
from .utils import Archive


_UA_STRING = 'instawow (https://github.com/layday/instawow)'

tqdm = partial(_tqdm, leave=False, ascii=True)


def _init_loop():
    try:
        import uvloop
    except ImportError:
        return asyncio.get_event_loop()
    else:
        return uvloop.new_event_loop()


def _dedupe(it):
    list_ = list(it)
    return sorted(set(list_), key=list_.index)


async def _intercept_fut(index, fut, return_exceptions):
    try:
        result = await fut
    except Exception as e:
        if return_exceptions:
            result = e
        else:
            raise
    return index, result


def _intercept_result(result, upd):
    if callable(result):
        try:
            result = result()
        except Exception as e:
            result = e
    upd()
    return result


class _DbOverlay:
    "Convenience methods for working with the database."

    def __init__(self, session):
        self._session = session

    def x_insert(self, obj):
        self._session.add(obj)
        self._session.commit()
        return obj

    def x_replace(self, obj, other=None):
        if other:
            self._session.delete(other)
            self._session.commit()
        return self.x_insert(obj)

    def x_delete(self, obj):
        self._session.delete(obj)
        self._session.commit()
        return obj

    def x_unique(self, origin, id_or_slug, kls=Pkg):
        return self._session.query(kls)\
                            .filter(kls.origin == origin,
                                    or_(kls.id == id_or_slug, kls.slug == id_or_slug))\
                            .first()


    def __getattr__(self, name):
        "Pass any other method call on to ye olde database session."
        return getattr(self._session, name)


class ManagerResult(Exception):
    pass


class PkgAlreadyInstalled(ManagerResult):
    pass


class PkgConflictsWithInstalled(ManagerResult):

    def __init__(self, pkg):
        super().__init__()
        self.conflicting_pkg = pkg


class PkgConflictsWithPreexisting(ManagerResult):
    pass


class PkgNonexistent(ManagerResult):
    pass


class PkgNotInstalled(ManagerResult):
    pass


class PkgOriginInvalid(ManagerResult):
    pass


class PkgUpToDate(ManagerResult):
    pass


class PkgInstalled(ManagerResult):

    def __init__(self, pkg):
        super().__init__()
        self.new_pkg = pkg


class PkgUpdated(ManagerResult):

    def __init__(self, pkgs):
        super().__init__()
        self.old_pkg, self.new_pkg = pkgs


class PkgModified(ManagerResult):

    def __init__(self, key, value):
        super().__init__()
        self.key = key
        self.value = value


class PkgRemoved(ManagerResult):
    pass


class CacheObsolete(ManagerResult):
    pass


class Manager:

    ManagerResult               = ManagerResult
    PkgInstalled                = PkgInstalled
    PkgUpdated                  = PkgUpdated
    PkgModified                 = PkgModified
    PkgRemoved                  = PkgRemoved
    PkgAlreadyInstalled         = PkgAlreadyInstalled
    PkgConflictsWithPreexisting = PkgConflictsWithPreexisting
    PkgConflictsWithInstalled   = PkgConflictsWithInstalled
    PkgNonexistent              = PkgNonexistent
    PkgNotInstalled             = PkgNotInstalled
    PkgOriginInvalid            = PkgOriginInvalid
    PkgUpToDate                 = PkgUpToDate
    CacheObsolete               = CacheObsolete

    def __init__(self,
                 *,
                 config: Config,
                 loop: asyncio.BaseEventLoop=_init_loop(),
                 show_progress: bool=True):
        self.config = config
        self.show_progress = show_progress

        db_engine = create_engine(f'sqlite:///{config.config_dir/config.db_name}')
        ModelBase.metadata.create_all(db_engine)
        self.db = _DbOverlay(sessionmaker(bind=db_engine)())

        self.client = ClientSession(connector=TCPConnector(limit_per_host=10, loop=loop),
                                    headers={'User-Agent': _UA_STRING}, loop=loop)
        self.resolvers = {n: r(manager=self)
                          for n, r in BaseResolver.__members__.items()}

        self._loop = loop
        self._resolver_lock = asyncio.Lock(loop=loop)
        self._tpes = [ThreadPoolExecutor(max_workers=1), ThreadPoolExecutor(max_workers=1)]

    async def block_in_thread(self, fn: T.Callable, *, channel: int=0) -> T.Any:
        """Execute a function in a separate thread.  Successive calls to this
        method are queued by virtue of reusing the same thread.
        """
        return await self._loop.run_in_executor(self._tpes[channel], fn)

    async def gather(self, it, *,
                     return_exceptions: bool=False,
                     **kwargs) -> list:
        """Convenience wrapper around ``asyncio.gather``.
        This displays a progress bar in the command line when
        `show_progress=True`.
        """
        if not self.show_progress:
            return await asyncio.gather(*it, loop=self._loop,
                                        return_exceptions=return_exceptions)

        futures = [_intercept_fut(i, f, return_exceptions)
                   for i, f in enumerate(it)]
        results = [None] * len(futures)
        with tqdm(total=len(futures), **kwargs) as bar:
            for result in asyncio.as_completed(futures, loop=self._loop):
                results.__setitem__(*(await result))
                bar.update(1)
        return results

    def __enter__(self) -> 'Manager':
        return self

    def __exit__(self, *_e):
        self.close()

    def close(self) -> None:
        self._loop.run_until_complete(self.client.close())

    async def _resolve(self, origin: str, id_or_slug: str,
                       strategy: str) -> T.Union[ManagerResult, Pkg]:
        if origin not in self.resolvers:
            raise PkgOriginInvalid

        async with self._resolver_lock:
            await self.resolvers[origin].sync()
        return await self.resolvers[origin].resolve(id_or_slug,
                                                    strategy=strategy)

    async def _prepare_install(self, origin: str, id_or_slug: str,
                               strategy: str, overwrite: bool) -> T.Callable:
        if self.db.x_unique(origin, id_or_slug):
            raise PkgAlreadyInstalled

        new_pkg = await self._resolve(origin, id_or_slug, strategy)
        async with self.client.get(new_pkg.download_url) as resp:
            payload = await resp.read()

        def _finalise():
            folder_conflict = \
                self.db.query(PkgFolder)\
                       .filter(PkgFolder.path.in_([f.path for f in new_pkg.folders]))\
                       .first()
            if folder_conflict:
                raise PkgConflictsWithInstalled(folder_conflict.pkg)
            try:
                Archive(payload).extract(self.config.addon_dir,
                                         overwrite=overwrite)
            except Archive.ExtractConflict:
                raise PkgConflictsWithPreexisting
            return PkgInstalled(self.db.x_insert(new_pkg))
        return _finalise

    async def _prepare_update(self, origin: str, id_or_slug: str) -> T.Callable:
        old_pkg = self.db.x_unique(origin, id_or_slug)
        if not old_pkg:
            raise PkgNotInstalled

        new_pkg = await self._resolve(origin, id_or_slug, old_pkg.options.strategy)
        if old_pkg.file_id == new_pkg.file_id:
            raise PkgUpToDate
        async with self.client.get(new_pkg.download_url) as resp:
            payload = await resp.read()

        def _finalise():
            folders = [f.path for f in new_pkg.folders]
            folder_conflict = \
                self.db.query(PkgFolder)\
                       .filter(PkgFolder.path.in_(folders),
                               PkgFolder.pkg_origin != new_pkg.origin,
                               PkgFolder.pkg_id != new_pkg.id)\
                       .first()
            if folder_conflict:
                raise PkgConflictsWithInstalled(folder_conflict.pkg)

            try:
                Archive(payload).extract(self.config.addon_dir,
                                         overwrite={f.name for f in folders})
            except Archive.ExtractConflict:
                raise PkgConflictsWithPreexisting
            return PkgUpdated((old_pkg, self.db.x_replace(new_pkg, old_pkg)))
        return _finalise

    def resolve_many(self, values: T.Iterable[tuple]) -> T.List[T.Union[ManagerResult, Pkg]]:
        return self._loop.run_until_complete(self.gather((self._resolve(*t) for t in _dedupe(values)),
                                                         return_exceptions=True,
                                                         show_progress=self.show_progress,
                                                         desc='Resolving'))

    def install_many(self, values: T.Iterable[tuple]) -> T.List[ManagerResult]:
        results = self._loop.run_until_complete(self.gather((self._prepare_install(*q)
                                                             for q in _dedupe(values)),
                                                            return_exceptions=True,
                                                            show_progress=self.show_progress,
                                                            desc='Resolving add-ons'))
        with tqdm(total=len(results), desc='Installing') as bar:
            return [_intercept_result(r, lambda: bar.update(1)) for r in results]

    def update_many(self, values: T.Iterable[tuple]) -> T.List[ManagerResult]:
        results = self._loop.run_until_complete(self.gather((self._prepare_update(*p)
                                                             for p in _dedupe(values)),
                                                            return_exceptions=True,
                                                            show_progress=self.show_progress,
                                                            desc='Resolving add-ons'))
        with tqdm(total=len(results), desc='Updating') as bar:
            return [_intercept_result(r, lambda: bar.update(1)) for r in results]

    def remove(self, origin: str, id_or_slug: str) -> PkgRemoved:
        pkg = self.db.x_unique(origin, id_or_slug)
        if not pkg:
            raise PkgNotInstalled

        for folder in pkg.folders:
            shutil.rmtree(folder.path)
        return PkgRemoved(self.db.x_delete(pkg))
