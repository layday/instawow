from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import contextvars as cv
from functools import partial
from itertools import filterfalse, repeat, starmap
from pathlib import Path, PurePath
import posixpath
from shutil import copy, move
from tempfile import NamedTemporaryFile, mkdtemp
from typing import (TYPE_CHECKING, Any, AsyncContextManager as ACM, AsyncGenerator, Awaitable,
                    Callable, Dict, Hashable, Iterable, List, NoReturn, Optional, Sequence, Set,
                    Tuple)

from loguru import logger

from . import DB_REVISION, exceptions as E
from .models import Pkg, PkgFolder, is_pkg
from .resolvers import CurseResolver, Defn, InstawowResolver, TukuiResolver, WowiResolver
from .utils import (bucketise, cached_property, dict_merge as merge, gather, make_progress_bar,
                    run_in_thread as t, shasum)

if TYPE_CHECKING:
    import aiohttp
    from prompt_toolkit.shortcuts import ProgressBar
    from sqlalchemy.orm import scoped_session
    from .config import Config


USER_AGENT = 'instawow (https://github.com/layday/instawow)'

_web_client: cv.ContextVar[aiohttp.ClientSession] = cv.ContextVar('_web_client')

AsyncNamedTemporaryFile = t(NamedTemporaryFile)
async_mkdtemp = t(mkdtemp)
async_copy = t(copy)
async_move = t(move)


@asynccontextmanager
async def open_temp_writer() -> AsyncGenerator[Tuple[Path, Callable], None]:
    fh = await AsyncNamedTemporaryFile(delete=False)
    path = Path(fh.name)
    try:
        yield (path, t(fh.write))
    except BaseException:
        await t(fh.close)()
        await t(path.unlink)()
        raise
    else:
        await t(fh.close)()


async def trash(paths: Sequence[Path], parent_dir: PurePath, *, missing_ok: bool = False) -> None:
    dst = await async_mkdtemp(dir=parent_dir, prefix=paths[0].name + '-')
    for path in map(str, paths):    # https://bugs.python.org/issue32689
        try:
            await async_move(path, dst)
        except (FileNotFoundError if missing_ok else ()):  # type: ignore  # https://github.com/python/mypy/issues/7356
            logger.opt(exception=True).info('source missing')


# macOS 'resource forks' are sometimes included in download zips - these
# violate our one add-on per folder contract-thing and will be omitted
_zip_excludes = {'__MACOSX'}


def find_base_dirs(names: Sequence[str]) -> Set[str]:
    return {n for n in (posixpath.dirname(n) for n in names)
            if n and posixpath.sep not in n} - _zip_excludes


def should_extract(base_dirs: Set[str]) -> Callable[[str], bool]:
    def is_member(name):
        head, sep, _ = name.partition(posixpath.sep)
        return sep and head in base_dirs

    return is_member


@asynccontextmanager
async def acquire_archive(path: PurePath) -> AsyncGenerator[Tuple[List[str], Callable], None]:
    from zipfile import ZipFile

    def extract(parent: Path) -> None:
        conflicts = base_dirs & {f.name for f in parent.iterdir()}
        if conflicts:
            raise E.PkgConflictsWithForeign(conflicts)
        else:
            members = filter(should_extract(base_dirs), names)
            archive.extractall(parent, members=members)

    archive = await t(ZipFile)(path)
    try:
        names = archive.namelist()
        base_dirs = find_base_dirs(names)
        yield (sorted(base_dirs), t(extract))
    finally:
        await t(archive.close)()


async def download_archive(manager: Manager, pkg: Pkg, *, chunk_size: int = 4096) -> ACM:
    url = pkg.download_url
    dst = manager.config.cache_dir / shasum(pkg.origin, pkg.id, pkg.file_id)

    if await t(dst.exists)():
        pass
    elif url.startswith('file://'):
        from urllib.parse import unquote

        await async_copy(unquote(url[7:]), dst)
    else:
        web_client = _web_client.get()
        async with web_client.get(url, trace_request_ctx={'show_progress': True}) as response, \
                open_temp_writer() as (temp_path, write):
            async for chunk in response.content.iter_chunked(chunk_size):
                await write(chunk)

        await async_move(str(temp_path), dst)
    return acquire_archive(dst)


def prepare_db_session(config: Config) -> scoped_session:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, scoped_session
    from .models import ModelBase, should_migrate

    db_path = config.config_dir / 'db.sqlite'
    db_url = f'sqlite:///{db_path}'
    # We need to distinguish between newly-created databases and
    # databases predating alembic in instawow - attempting to migrate a
    # new database will throw an error
    db_exists = db_path.exists()

    engine = create_engine(db_url)
    if should_migrate(engine, DB_REVISION):
        from .migrations import make_config, stamp, upgrade

        alembic_config = make_config(db_url)
        if db_exists:
            logger.info(f'migrating database to {DB_REVISION}')
            upgrade(alembic_config, DB_REVISION)
        else:
            ModelBase.metadata.create_all(engine)
            logger.info(f'stamping database with {DB_REVISION}')
            stamp(alembic_config, DB_REVISION)

    return scoped_session(sessionmaker(bind=engine))


def init_web_client(**kwargs: Any) -> aiohttp.ClientSession:
    from aiohttp import ClientSession, TCPConnector

    kwargs = {'connector': TCPConnector(force_close=True, limit_per_host=10),
              'headers': {'User-Agent': USER_AGENT},
              'trust_env': True,    # Respect http_proxy env var
              **kwargs}
    return ClientSession(**kwargs)


@object.__new__
class _DummyResolver:
    async def synchronise(self) -> _DummyResolver:
        return self

    async def resolve(self, defns: List[Defn], **kwargs: Any) -> Dict[Defn, E.PkgOriginInvalid]:
        return dict(zip(defns, repeat(E.PkgOriginInvalid())))


class _ResolverDict(dict):
    RESOLVERS = {CurseResolver, WowiResolver, TukuiResolver, InstawowResolver}

    def __init__(self, manager: Manager) -> None:
        super().__init__((r.source, r(manager=manager)) for r in self.RESOLVERS)

    def __missing__(self, key: Hashable) -> _DummyResolver:
        return _DummyResolver       # type: ignore      # unreported?


async def _error_out(error: E.ManagerError) -> NoReturn:
    raise error


class Manager:
    def __init__(self, config: Config, db_session: scoped_session) -> None:
        self.config = config
        self.db_session = db_session
        self.resolvers = _ResolverDict(self)

    @property
    def web_client(self) -> aiohttp.ClientSession:
        return _web_client.get()

    @web_client.setter
    def web_client(self, value: aiohttp.ClientSession) -> None:
        _web_client.set(value)

    def get(self, defn: Defn) -> Optional[Pkg]:
        return (self.db_session.query(Pkg)
                .filter(Pkg.origin == defn.source,
                        (Pkg.id == defn.name) | (Pkg.slug == defn.name)).first())

    def get_from_substr(self, defn: Defn) -> Optional[Pkg]:
        pkg = self.get(defn)
        if not pkg:
            pkg = (self.db_session.query(Pkg)
                   .filter(Pkg.slug.contains(defn.name)).order_by(Pkg.name).first())
        return pkg

    async def _resolve_deps(self, results: Iterable[Any]) -> Dict[Defn, Any]:
        """Resolve package dependencies.

        The resolver will not follow dependencies
        more than one level deep.  This is to avoid unnecessary
        complexity for something that I would never expect to
        encounter in the wild.
        """
        pkgs = list(filter(is_pkg, results))
        dep_defns = list(filterfalse({(p.origin, p.id) for p in pkgs}.__contains__,
                                     # Using a dict to maintain dep appearance order
                                     {(p.origin, d.id): ... for p in pkgs for d in p.deps}))
        if not dep_defns:
            return {}

        deps = await self.resolve(list(starmap(Defn, dep_defns)))
        pretty_deps = {d.with_name(r.slug) if is_pkg(r) else d: r for d, r in deps.items()}
        return pretty_deps

    async def resolve(self, defns: Sequence[Defn], with_deps: bool = False) -> Dict[Defn, Any]:
        "Resolve definitions into packages."
        async def get_results(source, defns):
            resolver = await self.resolvers[source].synchronise()
            return await resolver.resolve(defns)

        defns_by_source = bucketise(defns, key=lambda v: v.source)
        results = await gather(get_results(s, b) for s, b in defns_by_source.items())
        results_by_defn = merge(dict.fromkeys(defns), *results)
        if with_deps:
            results_by_defn.update(await self._resolve_deps(results_by_defn.values()))
        return results_by_defn

    async def search(self, search_terms: str, limit: int) -> Dict[Defn, Pkg]:
        "Search the combined names catalogue for packages."
        from fuzzywuzzy import fuzz, process
        from .resolvers import _FileCacheMixin as cache

        url = ('https://raw.githubusercontent.com/layday/instascrape/data/'
               'combined-names-v2.compact.json')   # v2
        combined_names = await cache._cache_json_response(self, url, 8, 'hours')
        defns_for_names = bucketise(((n, Defn(*d)) for n, d, f in combined_names
                                     if self.config.game_flavour in f),
                                    key=lambda v: v[0])

        matches = process.extract(search_terms, defns_for_names.keys(),
                                  limit=limit, scorer=fuzz.WRatio)
        defns = [d
                 for m, _ in matches
                 for _, d in defns_for_names[m]]
        results = await self.resolve(defns)
        pkgs_by_defn = {d.with_name(r.slug): r for d, r in results.items() if is_pkg(r)}
        return pkgs_by_defn

    async def install_one(self, pkg: Pkg, archive: ACM, replace: bool) -> E.PkgInstalled:
        async with archive as (folders, extract):
            conflicts = (self.db_session.query(Pkg).join(Pkg.folders)
                         .filter(PkgFolder.name.in_(folders)).all())
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts)
            if replace:
                await trash([self.config.addon_dir / f for f in folders], self.config.temp_dir)
            await extract(self.config.addon_dir)

        pkg.folders = [PkgFolder(name=f) for f in folders]
        self.db_session.add(pkg)
        self.db_session.commit()
        return E.PkgInstalled(pkg)

    async def prep_install(self, defns: Sequence[Defn], replace: bool) -> Dict[Defn, Callable]:
        "Retrieve packages to install."
        prelim_results = await self.resolve([d for d in defns if not self.get(d)],
                                            with_deps=True)
        # Weed out installed deps - this isn't super efficient but
        # avoids having to deal with local state in resolver
        results = {d: r for d, r in prelim_results.items() if not self.get(d)}
        installables = {(d, r): download_archive(self, r) for d, r in results.items() if is_pkg(r)}
        archives = await gather(installables.values())

        return merge(dict.fromkeys(defns, partial(_error_out, E.PkgAlreadyInstalled())),
                     {d: partial(_error_out, r) for d, r in results.items()},
                     {d: partial(self.install_one, p, a, replace)
                      for (d, p), a in zip(installables, archives)})

    async def update_one(self, old_pkg: Pkg, pkg: Pkg, archive: ACM) -> E.PkgUpdated:
        async with archive as (folders, extract):
            conflicts = (self.db_session.query(Pkg).join(Pkg.folders)
                         .filter(PkgFolder.pkg_origin != pkg.origin, PkgFolder.pkg_id != pkg.id)
                         .filter(PkgFolder.name.in_(folders)).all())
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts)

            await self.remove_one(old_pkg)
            await extract(self.config.addon_dir)

        pkg.folders = [PkgFolder(name=f) for f in folders]
        self.db_session.add(pkg)
        self.db_session.commit()
        return E.PkgUpdated(old_pkg, pkg)

    async def prep_update(self, defns: Sequence[Defn]) -> Dict[Defn, Callable]:
        "Retrieve packages to update."
        # Rebuild ``Defn`` with strategy from package for ``Defn``s
        # with installed packages
        checked_defns = {c.with_strategy(p.to_defn().strategy) if p else c: p
                         for c, p in ((d, self.get(d)) for d in defns)}
        # Results can contain errors
        # installables are those results which are packages
        # and updatables are packages with updates
        results = await self.resolve([d for d, p in checked_defns.items() if p])
        installables = {d: r for d, r in results.items() if is_pkg(r)}
        updatables = {(d, checked_defns[d], p): download_archive(self, p)
                      for d, p in installables.items()
                      if p.file_id != checked_defns[d].file_id}
        archives = await gather(updatables.values())

        return merge(dict.fromkeys(checked_defns, partial(_error_out, E.PkgNotInstalled())),
                     {d: partial(_error_out, r) for d, r in results.items()},
                     {d: partial(_error_out, E.PkgUpToDate()) for d in installables},
                     {d: partial(self.update_one, *p, a)
                      for (d, *p), a in zip(updatables, archives)})

    async def remove_one(self, pkg: Pkg) -> E.PkgRemoved:
        await trash([self.config.addon_dir / f.name for f in pkg.folders],
                    parent_dir=self.config.temp_dir, missing_ok=True)
        self.db_session.delete(pkg)
        self.db_session.commit()
        return E.PkgRemoved(pkg)

    async def prep_remove(self, defns: Sequence[Defn]) -> Dict[Defn, Callable]:
        "Prepare packages to remove."
        pkgs_by_defn = ((d, self.get(d)) for d in defns)
        return merge(dict.fromkeys(defns, partial(_error_out, E.PkgNotInstalled())),
                     {d: partial(self.remove_one, p) for d, p in pkgs_by_defn if p})


_tick_interval = .1
_tickers: cv.ContextVar[Set[asyncio.Task]] = cv.ContextVar('_tickers', default=set())


@asynccontextmanager
async def cancel_tickers() -> AsyncGenerator[None, None]:
    try:
        yield
    finally:
        for ticker in _tickers.get():
            ticker.cancel()


def init_cli_web_client(*, make_bar: ProgressBar) -> aiohttp.ClientSession:
    from cgi import parse_header
    from aiohttp import TraceConfig

    def extract_filename(params) -> str:
        _, cd_params = parse_header(params.response.headers.get('Content-Disposition', ''))
        filename = cd_params.get('filename') or params.response.url.name
        return filename

    async def do_on_request_end(session, request_ctx, params) -> None:
        ctx = request_ctx.trace_request_ctx
        if ctx and ctx.get('show_progress'):
            bar = make_bar(label=ctx.get('label') or f'Downloading {extract_filename(params)}',
                           total=params.response.content_length or 0)

            async def ticker() -> None:
                try:
                    content = params.response.content
                    while not content.is_eof():
                        bar.current = content._cursor
                        await asyncio.sleep(_tick_interval)
                finally:
                    bar.progress_bar.counters.remove(bar)

            tickers = _tickers.get()
            tickers.add(asyncio.create_task(ticker()))

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return init_web_client(trace_configs=[trace_config])


class CliManager(Manager):
    def __init__(self, config: Config, db_session: scoped_session,
                 progress_bar_factory: Callable = make_progress_bar) -> None:
        super().__init__(config, db_session)
        self.progress_bar_factory = progress_bar_factory

    @cached_property
    def progress_bar(self) -> Any:
        return self.progress_bar_factory()

    def run(self, awaitable: Awaitable) -> Any:
        async def run():
            async with init_cli_web_client(make_bar=self.progress_bar) as self.web_client, \
                    cancel_tickers():
                return await awaitable

        with self.progress_bar:
            return asyncio.run(run())

    def _prepprocess(self, prepper: Callable, *args: Any, **kwargs: Any) -> Dict[Defn, E.ManagerResult]:
        async def intercept(fn):
            try:
                return await fn()
            except E.ManagerError as error:
                return error
            except Exception as error:
                logger.exception('internal error')
                return E.InternalError(error)

        async def process():
            coros_by_defn = await prepper(*args, **kwargs)
            return {d: await intercept(c) for d, c in coros_by_defn.items()}

        return self.run(process())

    @property
    def install(self) -> Callable:
        return partial(self._prepprocess, self.prep_install)

    @property
    def update(self) -> Callable:
        return partial(self._prepprocess, self.prep_update)

    @property
    def remove(self) -> Callable:
        return partial(self._prepprocess, self.prep_remove)
