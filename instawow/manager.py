from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import contextvars as cv
from functools import partial
from pathlib import Path, PurePath
import posixpath
from shutil import move as _move
from tempfile import NamedTemporaryFile, mkdtemp
from typing import *

from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from . import db_version
from . import exceptions as E
from .models import ModelBase, Pkg, PkgFolder, should_migrate
from .resolvers import Defn, CurseResolver, WowiResolver, TukuiResolver, InstawowResolver
from .utils import (bucketise, cached_property, dict_merge, gather,
                    iter_or_repeat, make_progress_bar, run_in_thread)

if TYPE_CHECKING:
    from types import SimpleNamespace
    import aiohttp
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


async def move(paths: Iterable[Path], dest: PurePath) -> None:
    for path in paths:
        await async_move(str(path), dest)


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


def Archive(path: PurePath, delete_after: bool) -> Callable:
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
                path.unlink()   # type: ignore

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
        return Archive(path, delete_after=False)
    else:
        async with (_web_client.get()
                    .get(url, trace_request_ctx={'show_progress': True})) as response, \
                   open_temp_writer() as (path, write):
            async for chunk in response.content.iter_chunked(chunk_size):
                await write(chunk)
        return Archive(path, delete_after=True)


def prepare_db_session(config: Config) -> scoped_session:
    db_url = f"sqlite:///{config.config_dir / 'db.sqlite'}"
    engine = create_engine(db_url)
    ModelBase.metadata.create_all(engine)

    if should_migrate(engine, db_version):
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext
        from .migrations import make_config, stamp, upgrade

        with engine.begin() as conn:
            alembic_config = make_config(db_url)
            diff = compare_metadata(MigrationContext.configure(conn),
                                    ModelBase.metadata)
            if diff:
                logger.info(f'migrating database to {db_version}')
                upgrade(alembic_config, db_version)
            else:
                logger.info(f'stamping database with {db_version}')
                stamp(alembic_config, db_version)

    return scoped_session(sessionmaker(bind=engine))


async def init_web_client(**kwargs: Any) -> aiohttp.ClientSession:
    from aiohttp import ClientSession, TCPConnector

    kwargs = {'connector': TCPConnector(force_close=True, limit_per_host=10),
              'headers': {'User-Agent': USER_AGENT},
              'trust_env': True,
              **kwargs}
    return ClientSession(**kwargs)


class _DummyResolver:

    async def synchronise(*args: Any, **kwargs: Any) -> Type[_DummyResolver]:
        return _DummyResolver

    async def resolve(*args: Any, **kwargs: Any) -> NoReturn:
        raise E.PkgOriginInvalid


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

    def get(self, defn: Tuple[str, str]) -> Pkg:
        "Retrieve a package from the database."
        source, name = defn
        return (self.db_session.query(Pkg)
                .filter(Pkg.origin == source, (Pkg.id == name) | (Pkg.slug == name))
                .first())

    async def resolve(self, defns: Sequence[Defn], strategy: str) -> Dict[Defn, Any]:
        "Resolve a sequence of URIs into packages."
        defns_by_source = bucketise(defns, key=lambda v: v.source)
        results = await gather([((await self.resolvers[s].synchronise())
                                 .resolve(list(b), strategy))
                                for s, b in defns_by_source.items()])
        matched = dict_merge(dict.fromkeys(defns),
                             {d: r
                              for ds, rs in zip(defns_by_source.values(), results)
                              for d, r in zip(ds, iter_or_repeat(rs))})
        return matched

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

    async def prep_install(self, uris: Sequence[Defn], strategy: str, replace: bool) -> Dict[Defn, Coroutine]:
        "Retrieve packages to install."
        results = await self.resolve([u for u in uris if not self.get(u)], strategy)
        installables = {(u, r): download_archive(r) for u, r in results.items()
                        if isinstance(r, Pkg)}
        archives = await gather(installables.values())

        coros = {k: v() for k, v in
                 dict_merge(dict.fromkeys(uris, _error_wrapper(E.PkgAlreadyInstalled())),
                            {u: _error_wrapper(r) for u, r in results.items()},
                            {u: (lambda p=p, a=a: self._install(p, a, replace))
                             for (u, p), a in zip(installables, archives)}).items()}
        return coros

    async def _update(self, old_pkg: Pkg, new_pkg: Pkg, open_archive: Callable) -> E.PkgUpdated:
        async with open_archive() as (folders, extract):
            filter_ = (PkgFolder.name.in_(folders),
                       PkgFolder.pkg_origin != new_pkg.origin,
                       PkgFolder.pkg_id != new_pkg.id)
            conflicts = self.db_session.query(PkgFolder).filter(*filter_).first()
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts.pkg)

            temp_dir = await new_temp_dir(dir=self.config.temp_dir,
                                          prefix=f'{old_pkg.folders[0].name}-')
            await move((self.config.addon_dir / f.name for f in old_pkg.folders), temp_dir)
            await extract(self.config.addon_dir)

        new_pkg.folders = [PkgFolder(name=f) for f in folders]
        self.db_session.delete(old_pkg)
        self.db_session.add(new_pkg)
        self.db_session.commit()
        return E.PkgUpdated(old_pkg, new_pkg)

    async def prep_update(self, uris: Sequence[Defn]) -> Dict[Defn, Coroutine]:
        "Retrieve packages to update."
        candidates = {u: p for u, p in ((u, self.get(u)) for u in uris) if p}
        candidates_by_strategy = bucketise(candidates.items(),
                                           key=lambda v: v[1].options.strategy)
        results = dict_merge(*await gather(self.resolve([u for u, _ in c], s)
                                           for s, c in candidates_by_strategy.items()))
        installables = [(u, p) for u, p in results.items() if isinstance(p, Pkg)]
        updatables = {(u, p): download_archive(p) for u, p in installables
                      if p.file_id != candidates[u].file_id}
        archives = await gather(updatables.values())

        coros = {k: v() for k, v in
                 dict_merge(dict.fromkeys(uris, _error_wrapper(E.PkgNotInstalled())),
                            {u: _error_wrapper(r) for u, r in results.items()},
                            {u: _error_wrapper(E.PkgUpToDate()) for u, _ in installables},
                            {u: (lambda o=candidates[u], p=p, a=a: self._update(o, p, a))
                             for (u, p), a in zip(updatables, archives)}).items()}
        return coros

    async def _remove(self, pkg: Pkg) -> E.PkgRemoved:
        temp_dir = await new_temp_dir(dir=self.config.temp_dir,
                                      prefix=f'{pkg.folders[0].name}-')
        await move((self.config.addon_dir / f.name for f in pkg.folders), temp_dir)

        self.db_session.delete(pkg)
        self.db_session.commit()
        return E.PkgRemoved(pkg)

    async def prep_remove(self, uris: Sequence[Defn]) -> Dict[Defn, Coroutine]:
        "Prepare packages to remove."
        coros = {k: v() for k, v in
                 dict_merge(dict.fromkeys(uris, _error_wrapper(E.PkgNotInstalled())),
                            {u: (lambda p=p: self._remove(p))
                             for u, p in ((u, self.get(u)) for u in uris) if p}).items()}
        return coros


_tick_interval = .1
_tickers: cv.ContextVar[Set[asyncio.Task]] = cv.ContextVar('_tickers', default=set())


@asynccontextmanager
async def cancel_tickers() -> AsyncGenerator[None, None]:
    try:
        yield
    finally:
        for ticker in _tickers.get():
            ticker.cancel()


async def init_cli_web_client(*, manager: CliManager) -> aiohttp.ClientSession:
    "A web client that interfaces with the manager's progress bar."
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
        # Requests don't have a context unless they
        # originate from ``download_archive``
        if ctx.trace_request_ctx is None:
            return

        bar = manager.bar(label=f'Downloading {extract_filename(params)}',
                          total=params.response.content_length)

        async def ticker(bar=bar, params=params) -> None:
            try:
                while not params.response.content._eof:
                    bar.current = params.response.content._cursor
                    await asyncio.sleep(_tick_interval)
            finally:
                bar.progress_bar.counters.remove(bar)

        tickers = _tickers.get()
        tickers.add(asyncio.create_task(ticker()))

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return await init_web_client(trace_configs=[trace_config])


async def _intercept(coro: Coroutine) -> E.ManagerResult:
    try:
        return await coro
    except E.ManagerError as error:
        return error
    except Exception as error:
        logger.exception('internal error')
        return E.InternalError(error=error)


class CliManager(Manager):

    def __init__(self, config: Config, db_session: scoped_session,
                 progress_bar_factory: Optional[Callable] = None) -> None:
        super().__init__(config, db_session)
        self.progress_bar_factory = progress_bar_factory or make_progress_bar
        self.loop = asyncio.new_event_loop()

    @logger.catch(reraise=True)
    def _process(self, prepper: Callable,
                 uris: Sequence[Defn], *args: Any, **kwargs: Any) -> List[E.ManagerResult]:
        async def do_process():
            async with cancel_tickers():
                coros = await prepper(list(uris), *args, **kwargs)
                return [await _intercept(c) for c in coros.values()]

        with self.bar:
            return self.run(do_process())

    def run(self, awaitable: Awaitable) -> Any:
        "Run ``awaitable`` inside an explicit context."
        async def do_run():
            async with (await init_cli_web_client(manager=self)) as self.web_client:
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
