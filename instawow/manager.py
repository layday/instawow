from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import contextvars as cv
from functools import partial
from itertools import filterfalse, repeat, starmap
from pathlib import Path, PurePath
import posixpath
from shutil import move as _move
from tempfile import NamedTemporaryFile, mkdtemp
from typing import *

from loguru import logger

from . import DB_REVISION
from . import exceptions as E
from .models import Pkg, PkgFolder, is_pkg
from .resolvers import (Defn, Strategies,
                        CurseResolver, WowiResolver, TukuiResolver, InstawowResolver)
from .utils import (bucketise, cached_property, dict_merge, gather,
                    make_progress_bar, run_in_thread)

if TYPE_CHECKING:
    from types import SimpleNamespace
    import aiohttp
    from sqlalchemy.orm import scoped_session
    from .config import Config


USER_AGENT = 'instawow (https://github.com/layday/instawow)'

_web_client: cv.ContextVar[aiohttp.ClientSession] = cv.ContextVar('_web_client')

AsyncNamedTemporaryFile = partial(run_in_thread(NamedTemporaryFile), prefix='instawow-')
async_mkdtemp = run_in_thread(mkdtemp)
async_move = run_in_thread(_move)


@asynccontextmanager
async def open_temp_writer() -> AsyncGenerator[Tuple[Path, Callable], None]:
    fh = await AsyncNamedTemporaryFile(delete=False, suffix='.zip')
    try:
        yield (Path(fh.name), run_in_thread(fh.write))
    finally:
        await run_in_thread(fh.close)()


async def new_temp_dir(*args: Any, **kwargs: Any) -> PurePath:
    return PurePath(await async_mkdtemp(*args, **kwargs))


async def move(paths: Iterable[Path], dest: PurePath, *, missing_ok: bool = False) -> None:
    for path in paths:
        try:
            await async_move(str(path), dest)
        except (FileNotFoundError if missing_ok else ()):       # type: ignore
            logger.opt(exception=True).info('source missing')


# macOS 'resource forks' are sometimes included in download zips - these
# violate our one add-on per folder contract-thing, and serve absolutely
# no purpose.  They won't be extracted and they won't be added to the database
_zip_excludes = {'__MACOSX'}


def _find_base_dirs(names):
    return {n for n in (posixpath.dirname(n) for n in names)
            if n and posixpath.sep not in n} - _zip_excludes


def _should_extract(base_dirs):
    def is_member(name):
        head, sep, _ = name.partition(posixpath.sep)
        return sep and head in base_dirs

    return is_member


def Archive(path: Path, delete_after: bool) -> Callable:
    from zipfile import ZipFile

    @asynccontextmanager
    async def enter() -> AsyncGenerator[Tuple[List[str], Callable], None]:
        zip_file = await run_in_thread(ZipFile)(path)
        names = zip_file.namelist()
        base_dirs = _find_base_dirs(names)

        def extract(parent: Path) -> None:
            conflicts = base_dirs & {f.name for f in parent.iterdir()}
            if conflicts:
                raise E.PkgConflictsWithUncontrolled(conflicts)
            else:
                members = filter(_should_extract(base_dirs), names)
                zip_file.extractall(parent, members=members)

        def exit_() -> None:
            zip_file.close()
            if delete_after:
                path.unlink()

        try:
            yield (sorted(base_dirs), run_in_thread(extract))
        finally:
            await run_in_thread(exit_)()

    return enter


async def download_archive(pkg: Pkg, *, chunk_size: int = 4096) -> Callable:
    url = pkg.download_url
    if url.startswith('file://'):
        from urllib.parse import unquote

        path = PurePath(unquote(url[7:]))
        return Archive(path, delete_after=False)    # type: ignore
    else:
        async with (_web_client.get()
                    .get(url, trace_request_ctx={'show_progress': True})) as response, \
                   open_temp_writer() as (path, write):
            async for chunk in response.content.iter_chunked(chunk_size):
                await write(chunk)
        return Archive(path, delete_after=True)


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

    def __missing__(self, key: Hashable) -> Type[_DummyResolver]:
        return _DummyResolver


def _error_wrapper(error: E.ManagerError) -> Callable:
    async def error_out() -> NoReturn:
        raise error

    return error_out


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
        "Retrieve a package from the database."
        return (self.db_session.query(Pkg)
                .filter(Pkg.origin == defn.source,
                        (Pkg.id == defn.name) | (Pkg.slug == defn.name))
                .first())

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
        defns_by_source = bucketise(defns, key=lambda v: v.source)
        results = await gather([((await self.resolvers[s].synchronise())
                                 .resolve(list(b)))
                                for s, b in defns_by_source.items()])
        results_by_defn = dict_merge(dict.fromkeys(defns), *results)
        if with_deps:
            results_by_defn.update(await self._resolve_deps(results_by_defn.values()))
        return results_by_defn

    async def search(self, search_terms: str, limit: int, *,
                     scorer: str = 'partial_ratio') -> Dict[Defn, Pkg]:
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
                                  limit=limit, scorer=getattr(fuzz, scorer))
        defns = [d
                 for m, _ in matches
                 for _, d in defns_for_names[m]]
        results = await self.resolve(defns)
        pkgs_by_defn = {d.with_name(r.slug): r for d, r in results.items() if is_pkg(r)}
        return pkgs_by_defn

    async def _install(self, pkg: Pkg, open_archive: Callable, replace: bool) -> E.PkgInstalled:
        async with open_archive() as (folders, extract):
            conflicts = (self.db_session.query(PkgFolder)
                         .filter(PkgFolder.name.in_(folders)).all())
            if conflicts:
                raise E.PkgConflictsWithInstalled([c.pkg for c in conflicts])
            if replace:
                temp_dir = await new_temp_dir(dir=self.config.temp_dir, prefix=f'{folders[0]}-')
                await move((self.config.addon_dir / f for f in folders), temp_dir)
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
        installables = {(d, r): download_archive(r) for d, r in results.items() if is_pkg(r)}
        archives = await gather(installables.values())

        coros = (dict.fromkeys(defns, _error_wrapper(E.PkgAlreadyInstalled())),
                 {d: _error_wrapper(r) for d, r in results.items()},
                 {d: partial(self._install, p, a, replace)
                  for (d, p), a in zip(installables, archives)})
        return dict_merge(*coros)

    async def _update(self, old_pkg: Pkg, new_pkg: Pkg, open_archive: Callable) -> E.PkgUpdated:
        async with open_archive() as (folders, extract):
            filter_ = (PkgFolder.name.in_(folders),
                       PkgFolder.pkg_origin != new_pkg.origin,
                       PkgFolder.pkg_id != new_pkg.id)
            conflicts = self.db_session.query(PkgFolder).filter(*filter_).first()
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts.pkg)

            await self._remove(old_pkg)
            await extract(self.config.addon_dir)

        new_pkg.folders = [PkgFolder(name=f) for f in folders]
        self.db_session.add(new_pkg)
        self.db_session.commit()
        return E.PkgUpdated(old_pkg, new_pkg)

    async def prep_update(self, defns: Sequence[Defn]) -> Dict[Defn, Callable]:
        "Retrieve packages to update."
        def rebuild_defn(defn: Defn, pkg: Optional[Pkg]) -> Defn:
            return defn.with_strategy(Strategies[pkg.options.strategy]) if pkg else defn

        checked_defns = {rebuild_defn(c, p): p for c, p in ((d, self.get(d)) for d in defns)}
        candidates = {d: p for d, p in checked_defns.items() if p}
        results = await self.resolve(list(candidates.keys()))
        installables = {d: r for d, r in results.items() if is_pkg(r)}
        updatables = {(d, candidates[d], p): download_archive(p) for d, p in installables.items()
                      if p.file_id != candidates[d].file_id}
        archives = await gather(updatables.values())

        coros = (dict.fromkeys(checked_defns, _error_wrapper(E.PkgNotInstalled())),
                 {d: _error_wrapper(r) for d, r in results.items()},
                 {d: _error_wrapper(E.PkgUpToDate()) for d in installables},
                 {d: partial(self._update, o, p, a)
                  for (d, o, p), a in zip(updatables, archives)})
        return dict_merge(*coros)

    async def _remove(self, pkg: Pkg) -> E.PkgRemoved:
        temp_dir = await new_temp_dir(dir=self.config.temp_dir,
                                      prefix=f'{pkg.folders[0].name}-')
        await move((self.config.addon_dir / f.name for f in pkg.folders),
                   temp_dir, missing_ok=True)

        self.db_session.delete(pkg)
        self.db_session.commit()
        return E.PkgRemoved(pkg)

    async def prep_remove(self, defns: Sequence[Defn]) -> Dict[Defn, Callable]:
        "Prepare packages to remove."
        pkgs_by_defn = ((d, self.get(d)) for d in defns)
        coros = (dict.fromkeys(defns, _error_wrapper(E.PkgNotInstalled())),
                 {d: partial(self._remove, p) for d, p in pkgs_by_defn if p})
        return dict_merge(*coros)


_tick_interval = .1
_tickers: cv.ContextVar[Set[asyncio.Task]] = cv.ContextVar('_tickers', default=set())


@asynccontextmanager
async def cancel_tickers() -> AsyncGenerator[None, None]:
    try:
        yield
    finally:
        for ticker in _tickers.get():
            ticker.cancel()


def init_cli_web_client(*, manager: CliManager) -> aiohttp.ClientSession:
    from cgi import parse_header
    from aiohttp import TraceConfig

    def extract_filename(params: aiohttp.TraceRequestEndParams) -> str:
        cd = params.response.headers.get('Content-Disposition', '')
        _, cd_params = parse_header(cd)
        filename = cd_params.get('filename') or params.response.url.name
        return filename

    async def do_on_request_end(session: aiohttp.ClientSession,
                                ctx: SimpleNamespace,
                                params: aiohttp.TraceRequestEndParams) -> None:
        if ctx.trace_request_ctx and ctx.trace_request_ctx.get('show_progress'):
            label = (ctx.trace_request_ctx.get('label')
                     or f'Downloading {extract_filename(params)}')
            bar = manager.bar(label=label,
                              total=(params.response.content_length or 0))

            async def ticker(bar=bar, params=params) -> None:
                try:
                    while not params.response.content.is_eof():
                        bar.current = params.response.content._cursor
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
                 progress_bar_factory: Optional[Callable] = None) -> None:
        super().__init__(config, db_session)
        self.progress_bar_factory = progress_bar_factory or make_progress_bar
        self.loop = asyncio.new_event_loop()

    def get_from_substr(self, defn: Defn) -> Optional[Pkg]:
        pkg = self.get(defn)
        if not pkg:
            pkg = (self.db_session.query(Pkg)
                   .filter(Pkg.slug.contains(defn.name)).order_by(Pkg.name)
                   .first())
        return pkg

    def _process(self, prepper: Callable, uris: Sequence[Defn],
                 *args: Any, **kwargs: Any) -> Dict[Defn, E.ManagerResult]:
        async def intercept(fn: Callable) -> E.ManagerResult:
            try:
                return await fn()
            except E.ManagerError as error:
                return error
            except Exception as error:
                logger.exception('internal error')
                return E.InternalError(error)

        async def do_process():
            async with cancel_tickers():
                coros = await prepper(list(uris), *args, **kwargs)
                return {d: await intercept(c) for d, c in coros.items()}

        with self.bar:
            return self.run(do_process())

    def run(self, awaitable: Awaitable) -> Any:
        "Run ``awaitable`` inside an explicit context."
        async def do_run():
            async with init_cli_web_client(manager=self) as self.web_client:
                return await awaitable

        runner = lambda: self.loop.run_until_complete(do_run())
        return cv.copy_context().run(runner)

    @cached_property
    def bar(self) -> Any:
        return self.progress_bar_factory()

    @property
    def install(self) -> Callable:
        return partial(self._process, self.prep_install)

    @property
    def update(self) -> Callable:
        return partial(self._process, self.prep_update)

    @property
    def remove(self) -> Callable:
        return partial(self._process, self.prep_remove)
