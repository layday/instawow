
import asyncio
import contextvars
from functools import partial
import typing as T

from aiohttp import ClientSession, TCPConnector, TraceConfig
from send2trash import send2trash
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from tqdm import tqdm as _tqdm

from .config import Config
from . import exceptions as E
from .models import ModelBase, Pkg, PkgFolder
from .resolvers import BaseResolver
from .utils import Archive


_UA_STRING = 'instawow (https://github.com/layday/instawow)'


def init_loop():
    "Get a loop running."
    try:
        import uvloop
    except ImportError:
        return asyncio.get_event_loop()
    else:
        return uvloop.new_event_loop()


async def _init_client(*, loop, **kwargs):
    return ClientSession(loop=loop,
                         connector=TCPConnector(loop=loop, limit_per_host=10),
                         headers={'User-Agent': _UA_STRING},
                         **kwargs)


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
                                    (kls.id == id_or_slug) |
                                    (kls.slug == id_or_slug))\
                            .first()

    def __getattr__(self, name):
        # Pass any other method call on to ye olde database session
        return getattr(self._session, name)


class _MemberDict(dict):

    def __missing__(self, key):
        raise E.PkgOriginInvalid(origin=key)


_client = contextvars.ContextVar('_client')


class Manager:

    from .exceptions import (ManagerResult,
                             PkgInstalled, PkgUpdated, PkgRemoved,
                             ManagerError,
                             PkgAlreadyInstalled, PkgConflictsWithInstalled,
                             PkgConflictsWithPreexisting, PkgNonexistent,
                             PkgNotInstalled, PkgOriginInvalid,
                             PkgUpToDate, CacheObsolete,
                             InternalError)

    def __init__(self, *,
                 config: Config, loop: asyncio.BaseEventLoop=None,
                 client_factory: T.Callable=None):
        self.config = config
        self.loop = loop or init_loop()
        self.client_factory = client_factory or _init_client
        self.client = _client
        self.db = DbOverlay(config)
        self.resolvers = _MemberDict((n, r(manager=self))
                                     for n, r in BaseResolver.__members__.items())

    def run(self, awaitable: T.Awaitable) -> T.Any:
        "Run ``awaitable`` inside an explicit context."
        async def runner():
            async with (await self.client_factory(loop=self.loop)) as client:
                _client.set(client)
                return await awaitable

        return contextvars.copy_context().run(partial(self.loop.run_until_complete,
                                                      runner()))

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
        async with self.client.get()\
                              .get(new_pkg.download_url) as response:
            payload = await response.read()

        def finalise() -> E.PkgInstalled:
            archive = Archive(payload)
            new_pkg.folders = [PkgFolder(path=self.config.addon_dir/f)
                               for f in archive.root_folders]
            folder_conflict = self.db.query(PkgFolder)\
                                     .filter(PkgFolder.path.in_
                                              ([f.path for f in new_pkg.folders]))\
                                     .first()
            if folder_conflict:
                raise self.PkgConflictsWithInstalled(folder_conflict.pkg)
            try:
                archive.extract(parent_folder=self.config.addon_dir,
                                overwrite=overwrite)
            except Archive.ExtractConflict as conflict:
                raise self.PkgConflictsWithPreexisting(
                    folders=conflict.conflicting_folders)

            return self.PkgInstalled(self.db.x_insert(new_pkg))
        return finalise

    async def prepare_update(self, origin: str, id_or_slug: str,
                             strategy: str=None) -> T.Callable:
        """Retrieve a package to update.

        :raises: PkgOriginInvalid, PkgNonexistent,
                 PkgNotInstalled, PkgUpToDate,
                 PkgConflictsWithInstalled, PkgConflictsWithPreexisting,
                 CacheObsolete
        """
        old_pkg = self.db.x_unique(origin, id_or_slug)
        if not old_pkg:
            raise self.PkgNotInstalled
        new_pkg = await self.resolve(origin, id_or_slug,
                                     (strategy or old_pkg.options.strategy))
        if old_pkg.file_id == new_pkg.file_id:
            def finalise() -> None:
                if old_pkg.options.strategy != new_pkg.options.strategy:
                    old_pkg.options.strategy = new_pkg.options.strategy
                    self.db.commit()
                raise self.PkgUpToDate
            return finalise

        async with self.client.get()\
                              .get(new_pkg.download_url) as response:
            payload = await response.read()

        def finalise() -> E.PkgUpdated:
            archive = Archive(payload)
            new_pkg.folders = [PkgFolder(path=self.config.addon_dir/f)
                               for f in archive.root_folders]
            folder_conflict = self.db.query(PkgFolder)\
                                     .filter(PkgFolder.path.in_
                                              ([f.path for f in new_pkg.folders]),
                                             PkgFolder.pkg_origin != new_pkg.origin,
                                             PkgFolder.pkg_id != new_pkg.id)\
                                     .first()
            if folder_conflict:
                raise self.PkgConflictsWithInstalled(folder_conflict.pkg)

            try:
                archive.extract(parent_folder=self.config.addon_dir,
                                overwrite={f.path.name for f in new_pkg.folders})
            except Archive.ExtractConflict as conflict:
                raise self.PkgConflictsWithPreexisting(
                    folders=conflict.conflicting_folders)

            return self.PkgUpdated((old_pkg,
                                    self.db.x_replace(new_pkg, old_pkg)))
        return finalise

    def remove(self, origin: str, id_or_slug: str) -> E.PkgRemoved:
        """Remove a package.

        :raises: PkgNotInstalled
        """
        pkg = self.db.x_unique(origin, id_or_slug)
        if not pkg:
            raise self.PkgNotInstalled

        for folder in pkg.folders:
            send2trash(str(folder.path))
        return self.PkgRemoved(self.db.x_delete(pkg))

    async def gather(self, it: T.Iterable, **kwargs) -> list:
        "Overload for bespoke ``gather``ing."
        raise NotImplementedError


tqdm = partial(_tqdm, leave=False, ascii=True)

_dl_counter = contextvars.ContextVar('_dl_counter', default=0)


def _post_increment_dl_counter():
    val = _dl_counter.get()
    _dl_counter.set(val + 1)
    return val


async def _init_cli_client(*, loop):
    async def do_on_request_end(session, context, params):
        if (params.response.content_length and
                # Ignore files smaller than a megabyte
                params.response.content_length > 2**20):
            bar = tqdm(total=params.response.content_length,
                       desc=f'Downloading {params.response.url.name}',
                       miniters=1, unit='B', unit_scale=True,
                       position=_post_increment_dl_counter())

            async def ticker():
                while True:
                    if params.response.content._cursor == bar.total:
                        bar.close()
                        break
                    bar.update(params.response.content._cursor - bar.n)
                    # The polling frequency's gotta be high
                    # (higher than the ``tqdm.mininterval`` default)
                    # so this bar gets to flush itself down the proverbial
                    # drain before ``CliManager.gather``'s bar or it's gonna
                    # leave behind an empty line which would be, truly,
                    # devastating
                    await asyncio.sleep(.01)
            loop.create_task(ticker())

    trace_conf = TraceConfig()
    trace_conf.on_request_end.append(do_on_request_end)
    trace_conf.freeze()
    return await _init_client(loop=loop, trace_configs=[trace_conf])


async def _intercept_exc_async(index, awaitable):
    try:
        result = await awaitable
    except E.ManagerError as error:
        result = error
    except Exception as error:
        result = E.InternalError(error=error)
    return index, result


def _intercept_exc(callable_):
    try:
        result = callable_()
    except E.ManagerError as error:
        result = error
    except Exception as error:
        result = E.InternalError(error=error)
    return result


class CliManager(Manager):

    def __init__(self, *,
                 config: Config, loop: asyncio.BaseEventLoop=None,
                 show_progress: bool=True):
        self.show_progress = show_progress
        super().__init__(config=config, loop=loop,
                         client_factory=_init_cli_client if show_progress else None)

    async def gather(self, it: T.Iterable, **kwargs) -> list:
        futures = [_intercept_exc_async(*i) for i in enumerate(it)]
        results = [None] * len(futures)
        with tqdm(total=len(futures), disable=not self.show_progress,
                  position=_post_increment_dl_counter(), **kwargs) as bar:
            for result in asyncio.as_completed(futures, loop=self.loop):
                results.__setitem__(*await result)
                bar.update(1)
        return results

    def resolve_many(self, values: T.Iterable) -> list:
        return self.run(self.gather((self.resolve(*a)
                                     for a in values),
                                    desc='Resolving'))

    def install_many(self, values: T.Iterable) -> list:
        result = self.run(self.gather((self.prepare_new(*a)
                                       for a in values),
                                      desc='Fetching'))
        return [_intercept_exc(i) for i in result]

    def update_many(self,  values: T.Iterable) -> list:
        result = self.run(self.gather((self.prepare_update(*a)
                                       for a in values),
                                      desc='Checking'))
        return [_intercept_exc(i) for i in result]
