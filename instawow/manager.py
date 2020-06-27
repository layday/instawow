from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import contextvars as cv
from functools import partial
from itertools import filterfalse, starmap
import json
from pathlib import Path, PurePath
import posixpath
from shutil import copy, move
from tempfile import NamedTemporaryFile, mkdtemp
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager as ACM,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    NoReturn,
    Optional as O,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
    cast,
)

from loguru import logger

from . import DB_REVISION, exceptions as E
from .models import Pkg, PkgFolder, is_pkg
from .resolvers import (
    CurseResolver,
    Defn,
    InstawowResolver,
    MasterCatalogue,
    Resolver,
    TukuiResolver,
    WowiResolver,
)
from .utils import (
    bucketise,
    dict_chain,
    gather,
    is_not_stale,
    make_progress_bar,
    run_in_thread as t,
    shasum,
)

if TYPE_CHECKING:
    import aiohttp
    from prompt_toolkit.shortcuts import ProgressBar
    from sqlalchemy.orm import scoped_session
    from .config import Config

    _T = TypeVar('_T')
    _ArchiveR = Tuple[List[str], Callable[[Path], Awaitable[None]]]


USER_AGENT = 'instawow (https://github.com/layday/instawow)'

_web_client: cv.ContextVar[aiohttp.ClientSession] = cv.ContextVar('_web_client')

AsyncNamedTemporaryFile = t(NamedTemporaryFile)
amkdtemp = t(mkdtemp)
acopy = t(copy)
amove = t(move)


@asynccontextmanager
async def open_temp_writer() -> AsyncIterator[Tuple[Path, Callable[..., Any]]]:
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


async def trash(paths: Sequence[Path], parent: PurePath, *, missing_ok: bool = False) -> None:
    dst = await amkdtemp(dir=parent, prefix='deleted-' + paths[0].name + '-')
    for path in map(str, paths):  # https://bugs.python.org/issue32689
        try:
            await amove(path, dst)
        except (FileNotFoundError if missing_ok else ()):
            logger.opt(exception=True).info('source missing')


# macOS 'resource forks' are sometimes included in download zips - these
# violate our one add-on per folder contract-thing and will be omitted
_zip_excludes = {'__MACOSX'}


def find_base_dirs(names: Sequence[str]) -> Set[str]:
    return {
        n for n in (posixpath.dirname(n) for n in names) if n and posixpath.sep not in n
    } - _zip_excludes


def should_extract(base_dirs: Set[str]) -> Callable[[str], bool]:
    def is_member(name: str) -> bool:
        head, sep, _ = name.partition(posixpath.sep)
        return cast(bool, sep) and head in base_dirs

    return is_member


@asynccontextmanager
async def acquire_archive(path: PurePath) -> AsyncIterator[_ArchiveR]:
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


async def download_archive(
    manager: Manager, pkg: Pkg, *, chunk_size: int = 4096
) -> ACM[_ArchiveR]:
    url = pkg.download_url
    dst = manager.config.cache_dir / shasum(pkg.source, pkg.id, pkg.file_id)

    if await t(dst.exists)():
        pass
    elif url.startswith('file://'):
        from urllib.parse import unquote

        await acopy(unquote(url[7:]), dst)
    else:
        kwargs = {'raise_for_status': True, 'trace_request_ctx': {'show_progress': True}}
        async with manager.web_client.get(url, **kwargs) as response, open_temp_writer() as (
            temp_path,
            write,
        ):
            async for chunk in response.content.iter_chunked(chunk_size):
                await write(chunk)

        await amove(temp_path, dst)
    return acquire_archive(dst)


async def cache_json_response(manager: Manager, url: str, *args: Any, label: O[str] = None) -> Any:
    dst = manager.config.cache_dir / shasum(url)

    if await t(is_not_stale)(dst, *args):
        text = await t(dst.read_text)(encoding='utf-8')
    else:
        kwargs: Dict[str, Any] = {'raise_for_status': True}
        if label:
            kwargs.update({'trace_request_ctx': {'show_progress': True, 'label': label}})
        async with manager.web_client.get(url, **kwargs) as response:
            text = await response.text()

        await t(dst.write_text)(text, encoding='utf-8')
    return json.loads(text)


def prepare_db_session(config: Config) -> scoped_session:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker, scoped_session
    from .models import ModelBase, should_migrate

    db_path = config.config_dir / 'db.sqlite'
    db_url = f'sqlite:///{db_path}'
    # We can't perform a migration on a new database without "metadata"
    # and we need to check whether it exists before calling ``create_engine``,
    # which will implicitly create the database file
    db_exists = db_path.exists()

    engine = create_engine(db_url)
    if should_migrate(engine, DB_REVISION):
        from alembic.command import stamp, upgrade
        from alembic.config import Config as AConfig
        from .utils import copy_resources

        with copy_resources(
            f'{__package__}.migrations', f'{__package__}.migrations.versions'
        ) as tmp_dir:
            aconfig = AConfig()
            aconfig.set_main_option('script_location', str(tmp_dir / __package__ / 'migrations'))
            aconfig.set_main_option('sqlalchemy.url', db_url)

            if db_exists:
                logger.info(f'migrating database to {DB_REVISION}')
                upgrade(aconfig, DB_REVISION)
            else:
                ModelBase.metadata.create_all(engine)
                logger.info(f'stamping database with {DB_REVISION}')
                stamp(aconfig, DB_REVISION)

    return scoped_session(sessionmaker(bind=engine))


def init_web_client(**kwargs: Any) -> aiohttp.ClientSession:
    from aiohttp import ClientSession, ClientTimeout, TCPConnector

    kwargs = {
        'connector': TCPConnector(force_close=True, limit_per_host=10),
        'headers': {'User-Agent': USER_AGENT},
        'trust_env': True,  # Respect http_proxy env var
        'timeout': cast(Any, ClientTimeout)(connect=15),
        **kwargs,
    }
    return ClientSession(**kwargs)


@object.__new__
class _DummyResolver:
    async def synchronise(self) -> _DummyResolver:
        return self

    async def resolve(self, defns: List[Defn], **kwargs: Any) -> Dict[Defn, E.PkgSourceInvalid]:
        return dict.fromkeys(defns, E.PkgSourceInvalid())


class _ResolverDict(dict):
    def __missing__(self, key: str) -> Resolver:
        return _DummyResolver


async def _error_out(error: Union[E.ManagerError, E.InternalError]) -> NoReturn:
    raise error


class Manager:
    config: Config
    db_session: Any  # scoped_session
    resolvers: Mapping[str, Resolver]
    catalogue: MasterCatalogue

    def __init__(self, config: Config, db_session: scoped_session) -> None:
        self.config = config
        self.db_session = db_session

        resolvers = (CurseResolver, WowiResolver, TukuiResolver, InstawowResolver)
        self.resolvers = _ResolverDict({r.source: r(self) for r in resolvers})
        self.catalogue = None  # type: ignore

    @property
    def web_client(self) -> aiohttp.ClientSession:
        return _web_client.get()

    @web_client.setter
    def web_client(self, value: aiohttp.ClientSession) -> None:
        _web_client.set(value)

    def get(self, defn: Defn) -> O[Pkg]:
        "Get a package from (source, id) or (source, slug)."
        return (
            self.db_session.query(Pkg)
            .filter(Pkg.source == defn.source, (Pkg.id == defn.name) | (Pkg.slug == defn.name))
            .first()
        )

    def get_from_substr(self, defn: Defn) -> O[Pkg]:
        "Get a package from a partial slug."
        return self.get(defn) or (
            self.db_session.query(Pkg)
            .filter(Pkg.slug.contains(defn.name))
            .order_by(Pkg.name)
            .first()
        )

    def decompose_url(self, url: str) -> O[Tuple[str, str]]:
        "Parse a URL into a source–name tuple."
        for resolver in self.resolvers.values():
            name = resolver.decompose_url(url)
            if name:
                return resolver.source, name

    async def synchronise(self) -> None:
        "Fetch the master catalogue from the interwebs."
        if self.catalogue is None:
            label = 'Synchronising master catalogue'
            url = (
                'https://raw.githubusercontent.com/layday/instascrape/data/'
                'master-catalogue-v1.compact.json'
            )  # v1
            catalogue = await cache_json_response(self, url, 4, 'hours', label=label)
            self.catalogue = MasterCatalogue.parse_obj(catalogue)

    async def _consume_seq(
        self, coros_by_defn: Dict[Defn, Callable[..., Awaitable[Any]]]
    ) -> Dict[Defn, E.ManagerResult]:
        return {d: await E.ManagerResult.acapture(c()) for d, c in coros_by_defn.items()}

    async def _resolve_deps(self, results: Iterable[Any]) -> Dict[Defn, Any]:
        """Resolve package dependencies.

        The resolver will not follow dependencies
        more than one level deep.  This is to avoid unnecessary
        complexity for something that I would never expect to
        encounter in the wild.
        """
        pkgs = list(filter(is_pkg, results))
        dep_defns = list(
            filterfalse(
                {(p.source, p.id) for p in pkgs}.__contains__,
                # Using a dict to maintain dep appearance order
                {(p.source, d.id): ... for p in pkgs for d in p.deps},
            )
        )
        if not dep_defns:
            return {}

        deps = await self.resolve(list(starmap(Defn, dep_defns)))
        pretty_deps = {d.with_name(r.slug) if is_pkg(r) else d: r for d, r in deps.items()}
        return pretty_deps

    async def resolve(self, defns: Sequence[Defn], with_deps: bool = False) -> Dict[Defn, Any]:
        "Resolve definitions into packages."
        if not defns:
            return {}

        await self.synchronise()
        defns_by_source = bucketise(defns, key=lambda v: v.source)

        results = await gather(self.resolvers[s].resolve(b) for s, b in defns_by_source.items())
        results_by_defn = dict_chain(defns, None, *(r.items() for r in results))
        if with_deps:
            results_by_defn.update(await self._resolve_deps(results_by_defn.values()))
        return results_by_defn

    async def search(self, search_terms: str, limit: int) -> Dict[Defn, Pkg]:
        "Search the combined names catalogue for packages."
        import heapq
        import string
        from jellyfish import jaro_winkler

        trans_table = str.maketrans(dict.fromkeys(string.punctuation, ' '))

        def normalise(value: str):
            return value.casefold().translate(trans_table).strip()

        await self.synchronise()

        s = normalise(search_terms)
        tokens_to_defns = bucketise(
            (
                (normalise(i.name), (i.source, i.id))
                for i in self.catalogue.__root__
                if self.config.game_flavour in i.compatibility
            ),
            key=lambda v: v[0],
        )

        # TODO: weigh matches under threshold against download count
        matches = heapq.nlargest(
            limit, ((jaro_winkler(s, n), n) for n in tokens_to_defns.keys()), key=lambda v: v[0]
        )
        defns = [Defn(*d) for _, m in matches for _, d in tokens_to_defns[m]]
        results = await self.resolve(defns)
        pkgs_by_defn = {d.with_name(r.slug): r for d, r in results.items() if is_pkg(r)}
        return pkgs_by_defn

    async def install_one(
        self, pkg: Pkg, archive: ACM[_ArchiveR], replace: bool
    ) -> E.PkgInstalled:
        async with archive as (folders, extract):
            conflicts = (
                self.db_session.query(Pkg)
                .join(Pkg.folders)
                .filter(PkgFolder.name.in_(folders))
                .all()
            )
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts)

            if replace:
                await trash([self.config.addon_dir / f for f in folders], self.config.temp_dir)
            await extract(self.config.addon_dir)

        pkg.folders = [PkgFolder(name=f) for f in folders]
        self.db_session.add(pkg)
        self.db_session.commit()
        return E.PkgInstalled(pkg)

    async def install(self, defns: Sequence[Defn], replace: bool) -> Dict[Defn, E.ManagerResult]:
        prelim_results = await self.resolve([d for d in defns if not self.get(d)], with_deps=True)
        # Weed out installed deps - this isn't super efficient but avoids
        # having to deal with local state in the resolver
        results = {d: r for d, r in prelim_results.items() if not self.get(d)}
        installables = {(d, r): download_archive(self, r) for d, r in results.items() if is_pkg(r)}
        archives = await gather(installables.values())

        coros = dict_chain(
            defns,
            partial(_error_out, E.PkgAlreadyInstalled()),
            ((d, partial(_error_out, r)) for d, r in results.items()),
            (
                (d, partial(self.install_one, p, a, replace))
                for (d, p), a in zip(installables, archives)
            ),
        )
        return await self._consume_seq(coros)

    async def update_one(self, old_pkg: Pkg, pkg: Pkg, archive: ACM[_ArchiveR]) -> E.PkgUpdated:
        async with archive as (folders, extract):
            conflicts = (
                self.db_session.query(Pkg)
                .join(Pkg.folders)
                .filter(PkgFolder.pkg_source != pkg.source, PkgFolder.pkg_id != pkg.id)
                .filter(PkgFolder.name.in_(folders))
                .all()
            )
            if conflicts:
                raise E.PkgConflictsWithInstalled(conflicts)

            await self.remove_one(old_pkg)
            await extract(self.config.addon_dir)

        pkg.folders = [PkgFolder(name=f) for f in folders]
        self.db_session.add(pkg)
        self.db_session.commit()
        return E.PkgUpdated(old_pkg, pkg)

    async def update(self, defns: Sequence[Defn]) -> Dict[Defn, E.ManagerResult]:
        # Rebuild ``Defn`` with ID and strategy from package for defns
        # of installed packages.  Using the ID has the benefit of resolving
        # installed-but-renamed packages
        maybe_pkgs = ((d, self.get(d)) for d in defns)
        checked_defns = {Defn.from_pkg(p) if p else c: p for c, p in maybe_pkgs}

        # Results can contain errors
        # installables are those results which are packages
        # and updatables are packages with updates
        results = await self.resolve([d for d, p in checked_defns.items() if p])
        installables = {d: r for d, r in results.items() if is_pkg(r)}
        updatables = {
            (d, checked_defns[d], p): download_archive(self, p)
            for d, p in installables.items()
            if p.file_id != cast(Pkg, checked_defns[d]).file_id
        }
        archives = await gather(updatables.values())

        coros = dict_chain(
            checked_defns,
            partial(_error_out, E.PkgNotInstalled()),
            ((d, partial(_error_out, r)) for d, r in results.items()),
            ((d, partial(_error_out, E.PkgUpToDate())) for d in installables),
            ((d, partial(self.update_one, *p, a)) for (d, *p), a in zip(updatables, archives)),
        )
        return await self._consume_seq(coros)

    async def remove_one(self, pkg: Pkg) -> E.PkgRemoved:
        await trash(
            [self.config.addon_dir / f.name for f in pkg.folders],
            parent=self.config.temp_dir,
            missing_ok=True,
        )
        self.db_session.delete(pkg)
        self.db_session.commit()
        return E.PkgRemoved(pkg)

    async def remove(self, defns: Sequence[Defn]) -> Dict[Defn, E.ManagerResult]:
        pkgs_by_defn = ((d, self.get(d)) for d in defns)
        coros = dict_chain(
            defns,
            partial(_error_out, E.PkgNotInstalled()),
            ((d, partial(self.remove_one, p)) for d, p in pkgs_by_defn if p),
        )
        return await self._consume_seq(coros)


_tick_interval = 0.1
_tickers: cv.ContextVar[Set[asyncio.Task[None]]] = cv.ContextVar('_tickers', default=set())


@asynccontextmanager
async def cancel_tickers() -> AsyncIterator[None]:
    try:
        yield
    finally:
        for ticker in _tickers.get():
            ticker.cancel()


def init_cli_web_client(*, Bar: ProgressBar) -> aiohttp.ClientSession:
    from cgi import parse_header
    from aiohttp import TraceConfig, hdrs

    def extract_filename(response: aiohttp.ClientResponse) -> str:
        _, cd_params = parse_header(response.headers.get(hdrs.CONTENT_DISPOSITION, ''))
        filename = cd_params.get('filename') or response.url.name
        return filename

    async def do_on_request_end(session: Any, request_ctx: Any, params: Any) -> None:
        ctx = request_ctx.trace_request_ctx
        if not (ctx and ctx.get('show_progress')):
            return

        async def ticker() -> None:
            label = ctx.get('label') or f'Downloading {extract_filename(params.response)}'
            total = params.response.content_length
            if (
                total is None
                # Size before decoding is not exposed in streaming API and
                # `Content-Length` has the size of the payload after gzipping
                or params.response.headers.get(hdrs.CONTENT_ENCODING) == 'gzip'
            ):
                # Length of zero will have a hash sign cycle through the bar
                # (see indeterminate progress bars)
                total = 0

            bar = None
            try:
                bar = Bar(label=label, total=total)
                content = params.response.content

                while not content.is_eof():
                    # This is ``bar.current`` in prompt_toolkit v2
                    # and ``.items_completed`` in v3
                    bar.current = bar.items_completed = content.total_bytes
                    Bar.invalidate()
                    await asyncio.sleep(_tick_interval)
            finally:
                if bar is not None:
                    Bar.counters.remove(bar)

        tickers = _tickers.get()
        tickers.add(asyncio.create_task(ticker()))

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return init_web_client(trace_configs=[trace_config])


class CliManager(Manager):
    def run(self, awaitable: Awaitable[_T]) -> _T:
        async def run():
            async with init_cli_web_client(Bar=Bar) as self.web_client, cancel_tickers():
                return await awaitable

        with make_progress_bar() as Bar:
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(run())
            finally:
                loop.close()
