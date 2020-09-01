from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager, contextmanager
import contextvars as cv
from functools import partial
from itertools import chain, compress, filterfalse, repeat, starmap
import json
from pathlib import Path, PurePath
from shutil import copy
from tempfile import NamedTemporaryFile
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    DefaultDict,
    Dict,
    Iterable,
    Iterator,
    List,
    NoReturn,
    Optional as O,
    Sequence,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    cast,
)

from loguru import logger

from . import DB_REVISION, exceptions as E
from .models import Pkg, PkgFolder, PkgVersionLog, is_pkg
from .resolvers import (
    CurseResolver,
    Defn,
    GithubResolver,
    InstawowResolver,
    MasterCatalogue,
    Resolver,
    Strategies,
    TukuiResolver,
    WowiResolver,
)
from .utils import (
    bucketise,
    chain_dict,
    find_zip_base_dirs,
    gather,
    is_not_stale,
    make_progress_bar,
    make_zip_member_filter,
    move,
    run_in_thread as t,
    shasum,
    trash,
)

if TYPE_CHECKING:
    import aiohttp
    from prompt_toolkit.shortcuts import ProgressBar
    from sqlalchemy.orm import Session as SqlaSession
    from yarl import URL

    from .config import Config

    _T = TypeVar('_T')
    _ManagerT = TypeVar('_ManagerT', bound='Manager')


USER_AGENT = 'instawow (https://github.com/layday/instawow)'

_web_client: cv.ContextVar[aiohttp.ClientSession] = cv.ContextVar('_web_client')
_locks: cv.ContextVar[DefaultDict[str, asyncio.Lock]] = cv.ContextVar('_locks')


AsyncNamedTemporaryFile = t(NamedTemporaryFile)
copy_async = t(copy)
move_async = t(move)


@asynccontextmanager
async def _open_temp_writer() -> AsyncIterator[Tuple[Path, Callable[[bytes], Awaitable[int]]]]:
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


@contextmanager
def _open_archive(path: PurePath) -> Iterator[Tuple[Set[str], Callable[[Path], None]]]:
    from zipfile import ZipFile

    ZIP_EXCLUDES = {
        # Mac 'resource forks' are ommitted cuz they violate our one package
        # per folder policy-contract-thing (besides just being clutter)
        '__MACOSX',
    }

    with ZipFile(path) as archive:

        def extract(parent: Path) -> None:
            archive.extractall(parent, members=filter(make_zip_member_filter(base_dirs), names))

        names = archive.namelist()
        base_dirs = find_zip_base_dirs(names) - ZIP_EXCLUDES
        yield (base_dirs, extract)


async def download_archive(manager: Manager, pkg: Pkg, *, chunk_size: int = 4096) -> Path:
    url = pkg.download_url
    dest = manager.config.cache_dir / shasum(
        pkg.source, pkg.id, pkg.version, manager.config.game_flavour
    )
    if await t(dest.exists)():
        logger.debug(f'{url} is cached at {dest}')
    elif url.startswith('file://'):
        from urllib.parse import unquote

        await copy_async(unquote(url[7:]), dest)
    else:
        kwargs = {'raise_for_status': True, 'trace_request_ctx': {'report_progress': True}}
        async with manager.web_client.get(url, **kwargs) as response, _open_temp_writer() as (
            temp_path,
            write,
        ):
            async for chunk in response.content.iter_chunked(chunk_size):
                await write(chunk)

        await move_async(temp_path, dest)

    return dest


async def cache_json_response(
    manager: Manager,
    url: Union[str, URL],
    *timedelta_args: Any,
    label: O[str] = None,
    request_kwargs: Dict[str, Any] = {},
) -> Any:
    dest = manager.config.cache_dir / shasum(str(url), json.dumps(request_kwargs))
    if await t(is_not_stale)(dest, *timedelta_args):
        logger.debug(f'{url} is cached at {dest}')
        text = await t(dest.read_text)(encoding='utf-8')
    else:
        method = request_kwargs.pop('method', 'GET')
        kwargs = {'raise_for_status': True, **request_kwargs}
        if label:
            kwargs = {**kwargs, 'trace_request_ctx': {'report_progress': True, 'label': label}}
        async with manager.web_client.request(method, url, **kwargs) as response:
            text = await response.text()

        await t(dest.write_text)(text, encoding='utf-8')

    return json.loads(text)


def prepare_database(config: Config) -> SqlaSession:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from .models import ModelBase, should_migrate

    # We can't perform a migration on a new database without "metadata"
    # and we need to check whether it exists before calling ``create_engine``,
    # which will implicitly create the database file
    db_exists = config.db_file.exists()
    db_url = f'sqlite:///{config.db_file}'

    # We want to be able to reuse SQLite objects in a separate thread
    # when lumping database operations in with disk I/O,
    # not to lock up the loop
    engine = create_engine(db_url, connect_args={'check_same_thread': False})

    if should_migrate(engine, DB_REVISION):
        from alembic.command import stamp, upgrade
        from alembic.config import Config as AConfig

        from .utils import copy_resources

        with copy_resources(
            f'{__package__}.migrations',
            f'{__package__}.migrations.versions',
        ) as tmp_dir:
            aconfig = AConfig()
            aconfig.set_main_option('script_location', str(tmp_dir / __package__ / 'migrations'))
            aconfig.set_main_option('sqlalchemy.url', db_url)

            if db_exists:
                logger.info(f'migrating database at {config.db_file} to {DB_REVISION}')
                upgrade(aconfig, DB_REVISION)
            else:
                ModelBase.metadata.create_all(engine)
                logger.info(f'stamping database at {config.db_file} with {DB_REVISION}')
                stamp(aconfig, DB_REVISION)

    session_factory = sessionmaker(bind=engine)
    return session_factory()


def init_web_client(**kwargs: Any) -> aiohttp.ClientSession:
    from aiohttp import ClientSession, ClientTimeout, TCPConnector

    kwargs = {
        'connector': TCPConnector(force_close=True, limit_per_host=10),
        'headers': {'User-Agent': USER_AGENT},
        'trust_env': True,  # Respect the 'http_proxy' env var
        'timeout': cast(Any, ClientTimeout)(connect=15),
        **kwargs,
    }
    return ClientSession(**kwargs)


class _DummyLock:
    async def __aenter__(self) -> None:
        pass

    async def __aexit__(self, *args: Any) -> None:
        pass


@object.__new__
class _DummyResolver(Resolver):
    strategies = set()

    async def resolve(self, defns: Sequence[Defn]) -> Dict[Defn, E.PkgSourceInvalid]:
        return dict.fromkeys(defns, E.PkgSourceInvalid())


class _ResolverDict(Dict[str, Resolver]):
    def __missing__(self, key: str) -> Resolver:
        return _DummyResolver


def _error_out(error: BaseException) -> Callable[[], Awaitable[NoReturn]]:
    async def inner() -> NoReturn:
        raise error

    return inner


async def _capture_exc(coro: Callable[..., Awaitable[Any]]) -> E.ManagerResult:
    from aiohttp import ClientError

    try:
        return await coro()
    except E.ManagerError as error:
        return error
    except ClientError as error:
        logger.opt(exception=True).debug('network error')
        return E.InternalError(error, stringify_error=True)
    except BaseException as error:
        logger.exception('unclassed error')
        return E.InternalError(error)


class Manager:
    def __init__(
        self,
        config: Config,
        database: SqlaSession,
        catalogue: O[MasterCatalogue] = None,
        resolver_classes: Sequence[Type[Resolver]] = (
            CurseResolver,
            WowiResolver,
            TukuiResolver,
            GithubResolver,
            InstawowResolver,
        ),
    ) -> None:
        self.config = config
        self.database = database
        self.catalogue: MasterCatalogue = catalogue  # type: ignore
        self.resolvers = _ResolverDict((r.source, r(self)) for r in resolver_classes)

    @classmethod
    def from_config(cls: Type[_ManagerT], config: Config) -> _ManagerT:
        database = prepare_database(config)
        return cls(config, database)

    @property
    def web_client(self) -> aiohttp.ClientSession:
        "The web client session."
        try:
            return _web_client.get()
        except LookupError:
            task = asyncio.current_task()
            if task is None:
                raise RuntimeError('no running task')

            web_client = init_web_client()
            task.add_done_callback(lambda _: asyncio.create_task(web_client.close()))
            _web_client.set(web_client)
            logger.debug(f'initialised default web client with id {id(web_client)}')
            return web_client

    @web_client.setter
    def web_client(self, value: aiohttp.ClientSession) -> None:
        _web_client.set(value)

    @property
    def locks(self) -> DefaultDict[str, asyncio.Lock]:
        "Keeping things syncin'."
        try:
            return _locks.get()
        except LookupError:
            locks = cast('DefaultDict[str, asyncio.Lock]', defaultdict(_DummyLock))
            _locks.set(locks)
            logger.debug('using dummy lock factory')
            return locks

    @locks.setter
    def locks(self, value: DefaultDict[str, asyncio.Lock]) -> None:
        _locks.set(value)

    def _with_lock(
        lock_name: str,
        manager_bound: bool = True,  # type: ignore  # Undeclared static method
    ) -> Callable[[_T], _T]:
        def outer(coro_fn: _T):
            async def inner(self: Manager, *args: Any, **kwargs: Any):
                key = f'{id(self)}_{lock_name}' if manager_bound else lock_name
                async with self.locks[key]:
                    return await coro_fn(self, *args, **kwargs)

            return inner

        return outer

    def pair_uri(self, value: str) -> O[Tuple[str, str]]:
        "Attempt to extract the source from a URI."

        def from_urn():
            source, name = value.partition(':')[::2]
            if name:
                yield (source, name)

        url_pairs = filter(
            all, ((r.source, r.get_name_from_url(value)) for r in self.resolvers.values())
        )
        return next(
            chain(url_pairs, from_urn()),  # type: ignore
            None,
        )

    def get_pkg(self, defn: Defn, partial_match: bool = False) -> O[Pkg]:
        "Retrieve an installed package from a definition."
        return (
            (
                self.database.query(Pkg)
                .filter(
                    Pkg.source == defn.source,
                    (Pkg.id == defn.name) | (Pkg.slug == defn.name) | (Pkg.id == defn.source_id),
                )
                .first()
            )
            or partial_match
            and (
                self.database.query(Pkg)
                .filter(Pkg.slug.contains(defn.name))
                .order_by(Pkg.name)
                .first()
            )
            or None
        )

    def find_damaged_pkgs(self) -> List[Pkg]:
        "Find packages with missing folders."
        folders_in_db = {f.name for f in self.database.query(PkgFolder).all()}
        folders_on_disk = {f.name for f in self.config.addon_dir.iterdir()}
        folder_complement = folders_in_db - folders_on_disk
        damaged_pkgs = (
            self.database.query(Pkg)
            .join(PkgFolder)
            .filter(PkgFolder.name.in_(folder_complement))
            .all()
        )
        return damaged_pkgs

    def install_pkg(self, pkg: Pkg, archive: Path, replace: bool) -> E.PkgInstalled:
        "Install a package."
        with _open_archive(archive) as (top_level_folders, extract):
            installed_conflicts = (
                self.database.query(Pkg)
                .join(Pkg.folders)
                .filter(PkgFolder.name.in_(top_level_folders))
                .all()
            )
            if installed_conflicts:
                raise E.PkgConflictsWithInstalled(installed_conflicts)

            if replace:
                trash(
                    [self.config.addon_dir / f for f in top_level_folders],
                    dst=self.config.temp_dir,
                    missing_ok=True,
                )
            else:
                foreign_conflicts = top_level_folders & {
                    f.name for f in self.config.addon_dir.iterdir()
                }
                if foreign_conflicts:
                    raise E.PkgConflictsWithForeign(foreign_conflicts)

            extract(self.config.addon_dir)
            pkg.folders = [PkgFolder(name=f) for f in sorted(top_level_folders)]

        self.database.add(pkg)
        self.database.merge(
            PkgVersionLog(version=pkg.version, pkg_source=pkg.source, pkg_id=pkg.id)
        )
        self.database.commit()

        return E.PkgInstalled(pkg)

    def update_pkg(self, old_pkg: Pkg, new_pkg: Pkg, archive: Path) -> E.PkgUpdated:
        "Update a package."
        with _open_archive(archive) as (top_level_folders, extract):
            installed_conflicts = (
                self.database.query(Pkg)
                .join(Pkg.folders)
                .filter(PkgFolder.pkg_source != new_pkg.source, PkgFolder.pkg_id != new_pkg.id)
                .filter(PkgFolder.name.in_(top_level_folders))
                .all()
            )
            if installed_conflicts:
                raise E.PkgConflictsWithInstalled(installed_conflicts)

            foreign_conflicts = top_level_folders - {f.name for f in old_pkg.folders} & {
                f.name for f in self.config.addon_dir.iterdir()
            }
            if foreign_conflicts:
                raise E.PkgConflictsWithForeign(foreign_conflicts)

            trash(
                [self.config.addon_dir / f.name for f in old_pkg.folders],
                dst=self.config.temp_dir,
                missing_ok=True,
            )
            extract(self.config.addon_dir)
            new_pkg.folders = [PkgFolder(name=f) for f in sorted(top_level_folders)]

        self.database.delete(old_pkg)
        self.database.add(new_pkg)
        self.database.merge(
            PkgVersionLog(version=new_pkg.version, pkg_source=new_pkg.source, pkg_id=new_pkg.id)
        )
        self.database.commit()

        return E.PkgUpdated(old_pkg, new_pkg)

    def remove_pkg(self, pkg: Pkg) -> E.PkgRemoved:
        "Remove a package."
        trash(
            [self.config.addon_dir / f.name for f in pkg.folders],
            dst=self.config.temp_dir,
            missing_ok=True,
        )
        self.database.delete(pkg)
        self.database.commit()

        return E.PkgRemoved(pkg)

    @_with_lock('load master catalogue', False)
    async def synchronise(self) -> None:
        "Fetch the master catalogue from the interwebs and load it."
        if self.catalogue is None:
            label = 'Synchronising master catalogue'
            url = (
                'https://raw.githubusercontent.com/layday/instawow-data/data/'
                'master-catalogue-v1.compact.json'
            )  # v1
            raw_catalogue = await cache_json_response(self, url, 4, 'hours', label=label)
            self.catalogue = MasterCatalogue.parse_obj(raw_catalogue)

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

        deps = await self.resolve(list(starmap(Defn.get, dep_defns)))
        pretty_deps = {d.with_(name=r.slug) if is_pkg(r) else d: r for d, r in deps.items()}
        return pretty_deps

    async def resolve(self, defns: Sequence[Defn], with_deps: bool = False) -> Dict[Defn, Any]:
        "Resolve definitions into packages."
        if not defns:
            return {}

        await self.synchronise()

        defns_by_source = bucketise(defns, key=lambda v: v.source)
        results = await gather(self.resolvers[s].resolve(b) for s, b in defns_by_source.items())
        results_by_defn = chain_dict(
            defns,
            None,
            *(
                r.items() if isinstance(r, dict) else zip(d, repeat(r))
                for d, r in zip(defns_by_source.values(), results)
            ),
        )
        if with_deps:
            results_by_defn.update(await self._resolve_deps(results_by_defn.values()))
        return results_by_defn

    async def search(
        self, search_terms: str, limit: int, strategy: Strategies = Strategies.default
    ) -> Dict[Defn, Pkg]:
        "Search the master catalogue for packages by name."
        import heapq
        import string

        from jellyfish import jaro_winkler_similarity

        trans_table = str.maketrans(dict.fromkeys(string.punctuation, ' '))

        def normalise(value: str):
            return value.casefold().translate(trans_table).strip()

        await self.synchronise()

        s = normalise(search_terms)
        tokens_to_defns = bucketise(
            (
                (normalise(i.name), i)
                for i in self.catalogue.__root__
                if self.config.game_flavour in i.compatibility
            ),
            key=lambda v: v[0],
        )

        # TODO: weigh matches under threshold against download count
        matches = heapq.nlargest(
            limit,
            ((jaro_winkler_similarity(s, n), n) for n in tokens_to_defns),
            key=lambda v: v[0],
        )
        defns = [
            Defn.get(i.source, i.id).with_(strategy=strategy)
            for _, m in matches
            for _, i in tokens_to_defns[m]
        ]
        resolve_results = await self.resolve(defns)
        pkgs_by_defn = {d.with_(name=r.slug): r for d, r in resolve_results.items() if is_pkg(r)}
        return pkgs_by_defn

    @_with_lock('change state')
    async def install(self, defns: Sequence[Defn], replace: bool) -> Dict[Defn, E.ManagerResult]:
        "Install packages from a definition list."
        # We'll weed out installed dependencies from results after resolving.
        # Doing it this way isn't particularly efficient but avoids having to
        # deal with local state in resolvers.
        resolve_results = await self.resolve(
            list(compress(defns, (not self.get_pkg(d) for d in defns))),
            with_deps=True,
        )
        resolve_results = dict(
            compress(resolve_results.items(), (not self.get_pkg(d) for d in resolve_results))
        )
        installables = {
            (d, cast(Pkg, r)): download_archive(self, r)
            for d, r in resolve_results.items()
            if is_pkg(r)
        }
        archives = await gather(installables.values())
        result_coros = chain_dict(
            defns,
            _error_out(E.PkgAlreadyInstalled()),
            ((d, _error_out(r)) for d, r in resolve_results.items()),
            (
                (
                    d,
                    partial(t(self.install_pkg), p, a, replace)
                    if isinstance(a, PurePath)
                    else _error_out(a),
                )
                for (d, p), a in zip(installables, archives)
            ),
        )
        results = {d: await _capture_exc(c) for d, c in result_coros.items()}
        return results

    @_with_lock('change state')
    async def update(self, defns: Sequence[Defn]) -> Dict[Defn, E.ManagerResult]:
        "Update installed packages from a definition list."
        # Begin by rebuilding ``Defn`` with ID and strategy from package
        # for ``Defn``s of installed packages.  Using the ID has the benefit
        # of resolving installed-but-renamed packages -
        # the slug is transient but the ID is not.
        # Afterwards trim the results down to ``Defn``s with packages (installables)
        # and ``Defn``s with updates (updatables) and fetch the archives of
        # the latter class.
        maybe_pkgs = (self.get_pkg(d) for d in defns)
        defns_to_pkgs = {Defn.from_pkg(p) if p else d: p for d, p in zip(defns, maybe_pkgs)}
        resolve_results = await self.resolve([d for d, p in defns_to_pkgs.items() if p])
        installables = {d: cast(Pkg, r) for d, r in resolve_results.items() if is_pkg(r)}
        updatables = {
            (d, o, n): download_archive(self, n)
            for (d, n), o in zip(
                installables.items(), (cast(Pkg, defns_to_pkgs[d]) for d in installables)
            )
            if n.version != o.version
        }
        archives = await gather(updatables.values())
        result_coros = chain_dict(
            defns_to_pkgs,
            _error_out(E.PkgNotInstalled()),
            ((d, _error_out(r)) for d, r in resolve_results.items()),
            ((d, _error_out(E.PkgUpToDate())) for d in installables),
            (
                (
                    d,
                    partial(t(self.update_pkg), *p, a)
                    if isinstance(a, PurePath)
                    else _error_out(a),
                )
                for (d, *p), a in zip(updatables, archives)
            ),
        )
        results = {d: await _capture_exc(c) for d, c in result_coros.items()}
        return results

    @_with_lock('change state')
    async def remove(self, defns: Sequence[Defn]) -> Dict[Defn, E.ManagerResult]:
        "Remove packages by their definition."
        maybe_pkgs = (self.get_pkg(d) for d in defns)
        result_coros = chain_dict(
            defns,
            _error_out(E.PkgNotInstalled()),
            ((d, partial(t(self.remove_pkg), p)) for d, p in zip(defns, maybe_pkgs) if p),
        )
        results = {d: await _capture_exc(c) for d, c in result_coros.items()}
        return results

    @_with_lock('change state')
    async def pin(self, defns: Sequence[Defn]) -> Dict[Defn, E.ManagerResult]:
        """Pin and unpin installed packages.

        instawow does not have true pinning.  This sets the strategy
        to ``Strategies.version`` for installed packages from sources
        that support it.  The net effect is the same as if the package
        had been reinstalled with
        ``Defn(..., strategy=Strategies.version, strategy_vals=[pkg.version])``.
        Conversely a ``Defn`` with a ``Strategies.default`` will unpin the
        package.
        """

        strategies = {Strategies.default, Strategies.version}

        def pin(defns: Sequence[Defn]) -> Iterable[Tuple[Defn, E.ManagerResult]]:
            for defn in defns:
                pkg = self.get_pkg(defn)
                if pkg:
                    if {defn.strategy} <= strategies <= self.resolvers[pkg.source].strategies:
                        pkg.options.strategy = defn.strategy.name
                        self.database.commit()
                        yield (defn, E.PkgInstalled(pkg))
                    else:
                        yield (defn, E.PkgStrategyUnsupported(Strategies.version))
                else:
                    yield (defn, E.PkgNotInstalled())

        return dict(pin(defns))


def _extract_filename_from_hdr(response: aiohttp.ClientResponse) -> str:
    from cgi import parse_header

    from aiohttp import hdrs

    _, cd_params = parse_header(response.headers.get(hdrs.CONTENT_DISPOSITION, ''))
    filename = cd_params.get('filename') or response.url.name
    return filename


def _init_cli_web_client(
    bar: ProgressBar, tickers: Set[asyncio.Task[None]]
) -> aiohttp.ClientSession:
    from aiohttp import TraceConfig, hdrs

    async def do_on_request_end(
        client_session: aiohttp.ClientSession,
        trace_config_ctx: Any,
        params: aiohttp.TraceRequestEndParams,
    ) -> None:
        tick_interval = 0.1
        ctx = trace_config_ctx.trace_request_ctx
        if not (ctx and ctx.get('report_progress')):
            return

        async def ticker() -> None:
            label = (
                ctx.get('label') or f'Downloading {_extract_filename_from_hdr(params.response)}'
            )
            total = params.response.content_length
            # The encoded size is not exposed in the streaming API and
            # ``content_length`` has the size of the payload after gzipping -
            # we can't know what the actual size of a file is in transfer
            if params.response.headers.get(hdrs.CONTENT_ENCODING) == 'gzip':
                total = None

            counter = None
            try:
                counter = bar(label=label, total=total)
                content = params.response.content
                while not content.is_eof():
                    counter.items_completed = content.total_bytes
                    bar.invalidate()
                    await asyncio.sleep(tick_interval)
            finally:
                try:
                    bar.counters.remove(counter)
                except ValueError:
                    pass

        tickers.add(asyncio.create_task(ticker()))

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)  # type: ignore
    trace_config.freeze()
    return init_web_client(trace_configs=[trace_config])


@asynccontextmanager
async def _cancel_tickers(tickers: Set[asyncio.Task[None]]):
    try:
        yield
    finally:
        for ticker in tickers:
            ticker.cancel()


class CliManager(Manager):
    def run(self, awaitable: Awaitable[_T]) -> _T:
        with make_progress_bar() as bar:

            async def run():
                tickers = set()
                async with _init_cli_web_client(bar, tickers) as self.web_client, _cancel_tickers(
                    tickers
                ):
                    return await awaitable

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(run())
            finally:
                loop.close()
