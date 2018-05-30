
import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import shutil
import typing as T

from aiohttp import ClientSession, TCPConnector
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker
from tqdm import tqdm as _tqdm

from .config import Config
from . import exceptions as E
from .models import ModelBase, Pkg, PkgFolder
from .resolvers import BaseResolver
from .utils import Archive


_UA_STRING = 'instawow (https://github.com/layday/instawow)'

tqdm = partial(_tqdm, leave=False, ascii=True)


def init_loop():
    "Get a loop running."
    try:
        import uvloop
    except ImportError:
        return asyncio.get_event_loop()
    else:
        return uvloop.new_event_loop()


class DbOverlay:
    "Convenience wrapper for working with the database."

    def __init__(self, config: Config):
        db_engine = create_engine(f'sqlite:///{config.config_dir/config.db_name}')
        ModelBase.metadata.create_all(db_engine)
        self._session = sessionmaker(bind=db_engine)()

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

    @property
    def x_installed(self):
        return self._session.query(Pkg).order_by(Pkg.origin, Pkg.slug).all()

    def __getattr__(self, name):
        # Pass any other method call on to ye olde database session
        return getattr(self._session, name)


class _MemberDict(dict):

    def __missing__(self, key):
        raise E.PkgOriginInvalid(origin=key)


async def _init_client(loop):
    connector = TCPConnector(loop=loop, limit_per_host=10)
    return ClientSession(loop=loop, connector=connector,
                         headers={'User-Agent': _UA_STRING})


class Manager:

    from .exceptions import (ManagerResult,
                             PkgInstalled, PkgUpdated,
                             PkgModified, PkgRemoved,
                             ManagerError,
                             PkgAlreadyInstalled, PkgConflictsWithInstalled,
                             PkgConflictsWithPreexisting, PkgNonexistent,
                             PkgNotInstalled, PkgOriginInvalid,
                             PkgUpToDate, CacheObsolete,
                             InternalError)

    def __init__(self, *,
                 config: Config,
                 loop: asyncio.BaseEventLoop=None):
        self.config = config
        self.loop = loop or init_loop()
        self.db = DbOverlay(config)
        self.resolvers = _MemberDict((n, r(manager=self))
                                     for n, r in BaseResolver.__members__.items())
        self._tpes = [ThreadPoolExecutor(max_workers=1), ThreadPoolExecutor(max_workers=1)]

        # ``uvloop`` raises ``RuntimeError`` when client started outside async context
        self.wc = self.loop.run_until_complete(_init_client(self.loop))

    def __enter__(self):  # -> Manager
        return self

    def __exit__(self, *_e):
        self.close()

    def close(self) -> None:
        "Terminate this session."
        self.loop.run_until_complete(self.wc.close())

    async def resolve(self, origin: str, id_or_slug: str, strategy: str) -> Pkg:
        """Resolve an ID or slug into a ``Pkg``.

        :raises: PkgOriginInvalid, PkgNonexistent, CacheObsolete
        """
        return await self.resolvers[origin].resolve(id_or_slug, strategy=strategy)

    async def prepare_new(self, origin: str, id_or_slug: str,
                          strategy: str, overwrite: bool) -> T.Callable:
        """Retrieve a package to install.

        :raises: PkgOriginInvalid, PkgNonexistent, PkgAlreadyInstalled,
                 PkgConflictsWithInstalled, PkgConflictsWithPreexisting,
                 CacheObsolete
        """
        if self.db.x_unique(origin, id_or_slug):
            raise self.PkgAlreadyInstalled

        new_pkg = await self.resolve(origin, id_or_slug, strategy)
        async with self.wc.get(new_pkg.download_url) as resp:
            payload = await resp.read()

        def _finalise() -> E.PkgInstalled:
            folder_conflict = self.db.query(PkgFolder)\
                                     .filter(PkgFolder.path.in_([f.path for f in new_pkg.folders]))\
                                     .first()
            if folder_conflict:
                raise self.PkgConflictsWithInstalled(folder_conflict.pkg)
            try:
                Archive(payload).extract(parent_folder=self.config.addon_dir,
                                         overwrite=overwrite)
            except Archive.ExtractConflict:
                raise self.PkgConflictsWithPreexisting
            return self.PkgInstalled(self.db.x_insert(new_pkg))
        return _finalise

    async def prepare_update(self, origin: str, id_or_slug: str) -> T.Callable:
        """Retrieve a package to update.

        :raises: PkgOriginInvalid, PkgNonexistent, PkgNotInstalled, PkgUpToDate,
                 PkgConflictsWithInstalled, PkgConflictsWithPreexisting,
                 CacheObsolete
        """
        old_pkg = self.db.x_unique(origin, id_or_slug)
        if not old_pkg:
            raise self.PkgNotInstalled

        new_pkg = await self.resolve(origin, id_or_slug, old_pkg.options.strategy)
        if old_pkg.file_id == new_pkg.file_id:
            raise self.PkgUpToDate
        async with self.wc.get(new_pkg.download_url) as resp:
            payload = await resp.read()

        def _finalise() -> E.PkgUpdated:
            folder_conflict = self.db.query(PkgFolder)\
                                     .filter(PkgFolder.path.in_([f.path for f in new_pkg.folders]),
                                             PkgFolder.pkg_origin != new_pkg.origin,
                                             PkgFolder.pkg_id != new_pkg.id)\
                                     .first()
            if folder_conflict:
                raise self.PkgConflictsWithInstalled(folder_conflict.pkg)

            try:
                Archive(payload).extract(parent_folder=self.config.addon_dir,
                                         overwrite={f.path.name for f in new_pkg.folders})
            except Archive.ExtractConflict:
                raise self.PkgConflictsWithPreexisting
            return self.PkgUpdated((old_pkg, self.db.x_replace(new_pkg, old_pkg)))
        return _finalise

    def remove(self, origin: str, id_or_slug: str) -> E.PkgRemoved:
        """Remove a package.

        :raises: PkgNotInstalled
        """
        pkg = self.db.x_unique(origin, id_or_slug)
        if not pkg:
            raise self.PkgNotInstalled

        for folder in pkg.folders:
            shutil.rmtree(folder.path)
        return self.PkgRemoved(self.db.x_delete(pkg))

    async def block_in_thread(self, fn: T.Callable, *, channel: int=0) -> T.Any:
        """Execute a function in a separate thread.  Successive calls to this
        method are queued by virtue of reusing the same thread.
        """
        return await self.loop.run_in_executor(self._tpes[channel], fn)

    async def gather(self, it, **kwargs) -> list:
        "Overload for bespoke ``gather``ing."
        raise NotImplementedError


async def _intercept_exc(index, fut):
    try:
        result = await fut
    except E.ManagerError as error:
        result = error
    except Exception as error:
        result = E.InternalError(error=error)
    return index, result


def _run_multi(manager, fn, values, *, postprocess=None):
    uvalues = list(values)
    uvalues = sorted(set(uvalues), key=uvalues.index)
    results = manager.loop\
                     .run_until_complete(manager.gather((fn(*v) for v in uvalues),
                                                        desc='Resolving add-ons'))
    if postprocess:
        with tqdm(total=len(results),
                  disable=not manager.show_progress,
                  desc=postprocess) as bar:
            for i, result in enumerate(results):
                try:
                    results[i] = result()
                except E.ManagerError as error:
                    results[i] = error
                except Exception as error:
                    results[i] = E.InternalError(error=error)
                bar.update(1)
    return results


class CliManager(Manager):

    def __init__(self, *,
                 config: Config,
                 loop: asyncio.BaseEventLoop=None,
                 show_progress: bool=True):
        self.show_progress = show_progress
        super().__init__(config=config, loop=loop)

    async def gather(self, it, **kwargs) -> list:
        futures = [_intercept_exc(*i) for i in enumerate(it)]
        results = [None] * len(futures)
        with tqdm(total=len(futures), disable=not self.show_progress,
                  **kwargs) as bar:
            for result in asyncio.as_completed(futures, loop=self.loop):
                results.__setitem__(*await result)
                bar.update(1)
        return results

    def resolve_many(self, values):
        return _run_multi(self, self.resolve, values)

    def install_many(self, values):
        return _run_multi(self, self.prepare_new, values,
                          postprocess='Installing')

    def update_many(self, values):
        return _run_multi(self, self.prepare_update, values,
                          postprocess='Updating')
