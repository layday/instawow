from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Set,
)
from contextlib import asynccontextmanager, contextmanager
import contextvars as cv
from itertools import chain, compress, filterfalse, repeat, starmap
import json
from pathlib import Path, PurePath
from shutil import copy
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, TypeVar

from loguru import logger
from typing_extensions import TypeAlias

from . import DB_REVISION, results as E
from .config import Config
from .models import Pkg, PkgFolder, PkgVersionLog, is_pkg
from .plugins import load_plugins
from .resolvers import (
    Catalogue,
    CatalogueEntry,
    CurseResolver,
    Defn,
    GithubResolver,
    InstawowResolver,
    Resolver,
    Strategy,
    TownlongYakResolver,
    TukuiResolver,
    WowiResolver,
    normalise_names,
)
from .utils import (
    bucketise,
    chain_dict,
    copy_resources,
    file_uri_to_path,
    find_zip_base_dirs,
    gather,
    is_not_stale,
    make_progress_bar,
    make_zip_member_filter,
    move,
    run_in_thread as t,
    shasum,
    trash,
    uniq,
)

if TYPE_CHECKING:
    import aiohttp
    import prompt_toolkit.shortcuts
    import sqlalchemy.orm
    from yarl import URL

    _T = TypeVar('_T')
    _C = TypeVar('_C', bound=Callable[..., Awaitable[object]])
    _TManager = TypeVar('_TManager', bound='Manager')
    _BaseResolverDict: TypeAlias = 'dict[str, Resolver]'
else:
    _BaseResolverDict = dict


USER_AGENT = 'instawow (https://github.com/layday/instawow)'


_AsyncNamedTemporaryFile = t(NamedTemporaryFile)
_copy_async = t(copy)
_move_async = t(move)


@asynccontextmanager
async def _open_temp_writer() -> AsyncIterator[tuple[Path, Callable[[bytes], Awaitable[int]]]]:
    fh = await _AsyncNamedTemporaryFile(delete=False)
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
def _open_archive(path: PurePath) -> Iterator[tuple[set[str], Callable[[Path], None]]]:
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


async def _download_archive(manager: Manager, pkg: Pkg, *, chunk_size: int = 4096) -> Path:
    url = pkg.download_url
    dest = manager.config.cache_dir / shasum(
        pkg.source, pkg.id, pkg.version, manager.config.game_flavour
    )
    if await t(dest.exists)():
        logger.debug(f'retrieving {url} from cache at {dest}')
    elif url.startswith('file://'):
        await _copy_async(file_uri_to_path(url), dest)
    else:
        async with manager.web_client.get(
            url, raise_for_status=True, trace_request_ctx={'report_progress': True}
        ) as response, _open_temp_writer() as (
            temp_path,
            write,
        ):
            async for chunk in response.content.iter_chunked(chunk_size):
                await write(chunk)

        await _move_async(temp_path, dest)

    return dest


async def cache_response(
    manager: Manager,
    url: str | URL,
    ttl: Mapping[str, float],
    *,
    label: str | None = None,
    is_json: bool = True,
    request_extra: Mapping[str, Any] = {},
) -> Any:
    async def make_request():
        kwargs = {'method': 'GET', 'url': url, 'raise_for_status': True, **request_extra}
        if label:
            kwargs = {**kwargs, 'trace_request_ctx': {'report_progress': True, 'label': label}}
        async with manager.web_client.request(**kwargs) as response:
            return await response.text()

    dest = manager.config.cache_dir / shasum(url, request_extra)
    if await t(is_not_stale)(dest, ttl):
        logger.debug(f'loading {url} from cache at {dest} (ttl: {ttl})')
        text = await t(dest.read_text)(encoding='utf-8')
    else:
        text = await make_request()
        await t(dest.write_text)(text, encoding='utf-8')

    return json.loads(text) if is_json else text


def _should_migrate(engine: Any) -> bool:
    """Check if the database version is the same as ``DB_REVISION``;
    if not, a migration is required.

    Importing Alembic is prohibitively expensive in the CLI
    (adds about 250 ms to start-up time on my MBP) so we defer
    to SQLAlchemy.
    """
    from sqlalchemy import exc

    with engine.begin() as conn:
        try:
            current = conn.execute(
                'SELECT version_num FROM alembic_version WHERE version_num = (?)',
                DB_REVISION,
            ).scalar()
        except exc.OperationalError:
            return True
        else:
            return not current


def prepare_database(config: Config) -> sqlalchemy.orm.Session:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from .models import ModelBase

    engine = create_engine(
        f'sqlite:///{config.db_file}',
        # We wanna be able to operate on SQLite objects from
        # executor threads for convenience, when performing disk I/O
        connect_args={'check_same_thread': False},
    )

    if _should_migrate(engine):
        from alembic.command import stamp, upgrade
        from alembic.config import Config as AlembicConfig

        with copy_resources(
            f'{__package__}.migrations',
            f'{__package__}.migrations.versions',
        ) as tmp_dir:
            alembic_config = AlembicConfig()
            alembic_config.set_main_option(
                'script_location', str(tmp_dir / __package__ / 'migrations')
            )
            alembic_config.set_main_option('sqlalchemy.url', str(engine.url))

            if engine.table_names():
                upgrade(alembic_config, DB_REVISION)
            else:
                ModelBase.metadata.create_all(engine)
                stamp(alembic_config, DB_REVISION)

    return sessionmaker(bind=engine)()


def init_web_client(**kwargs: Any) -> aiohttp.ClientSession:
    from aiohttp import ClientSession, ClientTimeout, TCPConnector

    kwargs = {
        'connector': TCPConnector(force_close=True, limit_per_host=10),
        'headers': {'User-Agent': USER_AGENT},
        'trust_env': True,  # Respect the 'http_proxy' env var
        'timeout': ClientTimeout(connect=10, sock_read=10),  # type: ignore
        **kwargs,
    }
    return ClientSession(**kwargs)


@object.__new__
class _DummyResolver(Resolver):
    strategies = set()

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, Pkg | E.ManagerError | E.InternalError]:
        return dict.fromkeys(defns, E.PkgSourceInvalid())


class _ResolverDict(_BaseResolverDict):
    def __missing__(self, key: str) -> Resolver:
        return _DummyResolver


async def capture_manager_exc_async(
    awaitable: Awaitable[_T],
) -> _T | E.ManagerError | E.InternalError:
    "Capture and log an exception raised in a coroutine."
    from aiohttp import ClientError

    try:
        return await awaitable
    except (E.ManagerError, E.InternalError) as error:
        return error
    except ClientError as error:
        logger.opt(exception=True).debug('network error')
        return E.InternalError(error)
    except BaseException as error:
        logger.exception('unclassed error')
        return E.InternalError(error)


class _DummyLock:
    async def __aenter__(self) -> None:
        pass

    async def __aexit__(self, *args: object) -> None:
        pass


def _with_lock(
    lock_name: str,
    manager_bound: bool = True,
) -> Callable[[_C], _C]:
    def outer(coro_fn: _C) -> _C:
        async def inner(self: Manager, *args: object, **kwargs: object):
            async with self.locks[f'{id(self)}_{lock_name}' if manager_bound else lock_name]:
                return await coro_fn(self, *args, **kwargs)

        return inner  # type: ignore

    return outer


_web_client: cv.ContextVar[aiohttp.ClientSession] = cv.ContextVar('_web_client')

dummy_locks: defaultdict[str, Any] = defaultdict(_DummyLock)
_locks: cv.ContextVar[defaultdict[str, asyncio.Lock]] = cv.ContextVar(
    '_locks', default=dummy_locks
)


class Manager:
    RESOLVERS = (
        CurseResolver,
        WowiResolver,
        TukuiResolver,
        GithubResolver,
        InstawowResolver,
        TownlongYakResolver,
    )

    def __init__(
        self,
        config: Config,
        database: sqlalchemy.orm.Session,
    ) -> None:
        self.config = config
        self.database = database

        plugin_hook = load_plugins()
        resolver_classes = chain(
            (r for g in plugin_hook.instawow_add_resolvers() for r in g), self.RESOLVERS
        )
        self.resolvers = _ResolverDict((r.source, r(self)) for r in resolver_classes)

        self._catalogue = None

    @classmethod
    def contextualise(
        cls,
        *,
        web_client: aiohttp.ClientSession | None = None,
        locks: defaultdict[str, asyncio.Lock] | None = None,
    ) -> None:
        if web_client is not None:
            _web_client.set(web_client)
        if locks is not None:
            _locks.set(locks)

    @classmethod
    def from_config(cls: type[_TManager], config: Config) -> _TManager:
        return cls(config, prepare_database(config))

    @property
    def web_client(self) -> aiohttp.ClientSession:
        "The web client session."
        return _web_client.get()

    @property
    def locks(self) -> defaultdict[str, asyncio.Lock]:
        "Lock factory used to synchronise async operations."
        return _locks.get()

    def pair_uri(self, value: str) -> tuple[str, str] | None:
        "Attempt to extract the package source and alias from a URI."

        def from_urn():
            source, alias = value.partition(':')[::2]
            if alias:
                yield (source, alias)

        url_pairs: Iterator[tuple[str, Any]] = filter(
            all, ((r.source, r.get_alias_from_url(value)) for r in self.resolvers.values())
        )
        return next(chain(url_pairs, from_urn()), None)

    def get_pkg(self, defn: Defn, partial_match: bool = False) -> Pkg | None:
        "Retrieve an installed package from a definition."
        return (
            (
                self.database.query(Pkg)
                .filter(
                    Pkg.source == defn.source,
                    (Pkg.id == defn.alias) | (Pkg.slug == defn.alias) | (Pkg.id == defn.id),
                )
                .first()
            )
            or partial_match
            and (
                self.database.query(Pkg)
                .filter(Pkg.slug.contains(defn.alias))
                .order_by(Pkg.name)
                .first()
            )
            or None
        )

    def install_pkg(self, pkg: Pkg, archive: Path, replace: bool) -> E.PkgInstalled:
        "Install a package."
        with _open_archive(archive) as (top_level_folders, extract):
            installed_conflicts: list[Pkg] = (
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
                    dest=self.config.temp_dir,
                    missing_ok=True,
                )
            else:
                unreconciled_conflicts = top_level_folders & {
                    f.name for f in self.config.addon_dir.iterdir()
                }
                if unreconciled_conflicts:
                    raise E.PkgConflictsWithUnreconciled(unreconciled_conflicts)

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
            installed_conflicts: list[Pkg] = (
                self.database.query(Pkg)
                .join(Pkg.folders)
                .filter(PkgFolder.pkg_source != new_pkg.source, PkgFolder.pkg_id != new_pkg.id)
                .filter(PkgFolder.name.in_(top_level_folders))
                .all()
            )
            if installed_conflicts:
                raise E.PkgConflictsWithInstalled(installed_conflicts)

            unreconciled_conflicts = top_level_folders - {f.name for f in old_pkg.folders} & {
                f.name for f in self.config.addon_dir.iterdir()
            }
            if unreconciled_conflicts:
                raise E.PkgConflictsWithUnreconciled(unreconciled_conflicts)

            trash(
                [self.config.addon_dir / f.name for f in old_pkg.folders],
                dest=self.config.temp_dir,
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

    def remove_pkg(self, pkg: Pkg, keep_folders: bool) -> E.PkgRemoved:
        "Remove a package."
        if not keep_folders:
            trash(
                [self.config.addon_dir / f.name for f in pkg.folders],
                dest=self.config.temp_dir,
                missing_ok=True,
            )
        self.database.delete(pkg)
        self.database.commit()

        return E.PkgRemoved(pkg)

    @_with_lock('load catalogue', False)
    async def synchronise(self) -> Catalogue:
        "Fetch the catalogue from the interwebs and load it."
        if self._catalogue is None:
            label = 'Synchronising catalogue'
            url = (
                'https://raw.githubusercontent.com/layday/instawow-data/data/'
                'master-catalogue-v2.compact.json'
            )  # v2
            raw_catalogue = await cache_response(self, url, {'hours': 4}, label=label)
            self._catalogue = Catalogue.parse_obj(raw_catalogue)
        return self._catalogue

    async def _resolve_deps(self, results: Iterable[Any]) -> dict[Defn, Any]:
        """Resolve package dependencies.

        The resolver will not follow dependencies
        more than one level deep.  This is to avoid unnecessary
        complexity for something that I would never expect to
        encounter in the wild.
        """
        pkgs = [r for r in results if is_pkg(r)]
        dep_defns = uniq(
            filterfalse(
                {(p.source, p.id) for p in pkgs}.__contains__,
                ((p.source, d.id) for p in pkgs for d in p.deps),
            )
        )
        if not dep_defns:
            return {}

        deps = await self.resolve(list(starmap(Defn, dep_defns)))
        pretty_deps = {d.with_(alias=r.slug) if is_pkg(r) else d: r for d, r in deps.items()}
        return pretty_deps

    async def resolve(self, defns: Sequence[Defn], with_deps: bool = False) -> dict[Defn, Any]:
        "Resolve definitions into packages."
        if not defns:
            return {}

        defns_by_source = bucketise(defns, key=lambda v: v.source)
        results = await gather(
            (self.resolvers[s].resolve(b) for s, b in defns_by_source.items()),
            capture_manager_exc_async,
        )
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
        self,
        search_terms: str,
        limit: int,
        sources: Set[str] | None = None,
    ) -> list[CatalogueEntry]:
        "Search the master catalogue for packages by name."
        import heapq

        from jellyfish import jaro_winkler_similarity

        catalogue = await self.synchronise()

        w = 0.5  # Weighing edit distance and download score equally
        normalise = normalise_names()

        if sources is None:
            sources = self.resolvers.keys()

        s = normalise(search_terms)
        tokens_to_entries = bucketise(
            (
                (i.normalised_name, i)
                for i in catalogue.__root__
                if self.config.game_flavour in i.game_compatibility and i.source in sources
            ),
            key=lambda v: v[0],
        )
        matches = heapq.nlargest(
            limit,
            ((jaro_winkler_similarity(s, n), n) for n in tokens_to_entries),
            key=lambda v: v[0],
        )
        weighted_entries = sorted(
            (
                (-(s * w + i.derived_download_score * (1 - w)), i)
                for s, m in matches
                for _, i in tokens_to_entries[m]
            ),
            key=lambda v: v[0],
        )
        return [e for _, e in weighted_entries]

    @_with_lock('change state')
    async def install(
        self, defns: Sequence[Defn], replace: bool
    ) -> dict[Defn, E.PkgInstalled | E.ManagerError | E.InternalError]:
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
            (d, r): _download_archive(self, r) for d, r in resolve_results.items() if is_pkg(r)
        }
        archives = await gather(installables.values(), capture_manager_exc_async)
        results = chain_dict(
            defns,
            E.PkgAlreadyInstalled(),
            resolve_results.items(),
            ((d, a) for (d, _), a in zip(installables, archives) if not isinstance(a, PurePath)),
            [
                (d, await capture_manager_exc_async(t(self.install_pkg)(p, a, replace)))
                for (d, p), a in zip(installables, archives)
                if isinstance(a, PurePath)
            ],
        )
        return results

    @_with_lock('change state')
    async def update(
        self, defns: Sequence[Defn], retain_strategy: bool
    ) -> dict[Defn, E.PkgUpdated | E.ManagerError | E.InternalError]:
        """Update installed packages from a definition list.

        A ``retain_strategy`` value of false will instruct ``update``
        to extract the strategy from the installed package; otherwise
        the ``Defn`` strategy will be used.
        """
        defns_to_pkgs = {d: p for d in defns for d, p in ((d, self.get_pkg(d)),) if p}
        resolve_defns = {
            # Attach the source ID to each ``Defn`` from the
            # corresponding installed package.  Using the ID has the benefit
            # of resolving installed-but-renamed packages - the slug is
            # transient but the ID isn't
            d.with_(id=p.id) if retain_strategy else Defn.from_pkg(p): d
            for d, p in defns_to_pkgs.items()
        }
        # Discard the reconstructed ``Defn``s
        resolve_results = {
            resolve_defns[d]: r for d, r in (await self.resolve(list(resolve_defns))).items()
        }
        installables = {d: r for d, r in resolve_results.items() if is_pkg(r)}
        updatables = {
            (d, o, n): _download_archive(self, n)
            for d, n in installables.items()
            for d, o, n in ((d, defns_to_pkgs[d], n),)
            if n.version != o.version
        }
        archives = await gather(updatables.values(), capture_manager_exc_async)
        results = chain_dict(
            defns,
            E.PkgNotInstalled(),
            resolve_results.items(),
            (
                (d, E.PkgUpToDate(is_pinned=p.options.strategy == Strategy.version))
                for d, p in installables.items()
            ),
            ((d, a) for (d, *_), a in zip(updatables, archives) if not isinstance(a, PurePath)),
            [
                (d, await capture_manager_exc_async(t(self.update_pkg)(o, n, a)))
                for (d, o, n), a in zip(updatables, archives)
                if isinstance(a, PurePath)
            ],
        )
        return results

    @_with_lock('change state')
    async def remove(
        self, defns: Sequence[Defn], keep_folders: bool
    ) -> dict[Defn, E.PkgRemoved | E.ManagerError | E.InternalError]:
        "Remove packages by their definition."
        results = chain_dict(
            defns,
            E.PkgNotInstalled(),
            [
                (d, await capture_manager_exc_async(t(self.remove_pkg)(p, keep_folders)))
                for d in defns
                for d, p in ((d, self.get_pkg(d)),)
                if p
            ],
        )
        return results

    @_with_lock('change state')
    async def pin(
        self, defns: Sequence[Defn]
    ) -> dict[
        Defn,
        E.PkgNotInstalled
        | E.PkgInstalled
        | E.PkgStrategyUnsupported
        | E.ManagerError
        | E.InternalError,
    ]:
        """Pin and unpin installed packages.

        instawow does not have true pinning.  This sets the strategy
        to ``Strategies.version`` for installed packages from sources
        that support it.  The net effect is the same as if the package
        had been reinstalled with the version strategy.
        Conversely a ``Defn`` with the default strategy will unpin the
        package.
        """

        strategies = frozenset({Strategy.default, Strategy.version})

        def pin(
            defn: Defn, pkg: Pkg | None
        ) -> E.PkgNotInstalled | E.PkgInstalled | E.PkgStrategyUnsupported:
            if not pkg:
                return E.PkgNotInstalled()
            elif {defn.strategy} <= strategies <= self.resolvers[pkg.source].strategies:
                pkg.options.strategy = defn.strategy
                self.database.commit()
                return E.PkgInstalled(pkg)
            else:
                return E.PkgStrategyUnsupported(Strategy.version)

        return {d: await capture_manager_exc_async(t(pin)(d, self.get_pkg(d))) for d in defns}


def _extract_filename_from_hdr(response: aiohttp.ClientResponse) -> str:
    from cgi import parse_header

    from aiohttp import hdrs

    _, cd_params = parse_header(response.headers.get(hdrs.CONTENT_DISPOSITION, ''))
    filename = cd_params.get('filename') or response.url.name
    return filename


def _init_cli_web_client(
    bar: prompt_toolkit.shortcuts.ProgressBar, tickers: set[asyncio.Task[None]]
) -> aiohttp.ClientSession:
    from aiohttp import TraceConfig, TraceRequestEndParams, hdrs

    async def do_on_request_end(
        client_session: aiohttp.ClientSession,
        trace_config_ctx: Any,
        params: TraceRequestEndParams,
    ) -> None:
        tick_interval = 0.1
        ctx = trace_config_ctx.trace_request_ctx
        if not (ctx and ctx.get('report_progress')):
            return

        async def ticker() -> None:
            response = params.response
            label = ctx.get('label') or f'Downloading {_extract_filename_from_hdr(response)}'

            total = response.content_length
            # The encoded size is not exposed in the streaming API and
            # ``content_length`` has the size of the payload after gzipping -
            # we can't know what the actual size of a file is in transfer
            if response.headers.get(hdrs.CONTENT_ENCODING) == 'gzip':
                total = None

            counter = bar(label=label, total=total)
            try:
                while not response.content.is_eof():
                    counter.items_completed = response.content.total_bytes
                    bar.invalidate()
                    await asyncio.sleep(tick_interval)
            finally:
                bar.counters.remove(counter)

        tickers.add(asyncio.create_task(ticker()))

    trace_config = TraceConfig()
    trace_config.on_request_end.append(do_on_request_end)
    trace_config.freeze()
    return init_web_client(trace_configs=[trace_config])


@asynccontextmanager
async def _cancel_tickers(tickers: set[asyncio.Task[None]]):
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
                async with _init_cli_web_client(bar, tickers) as web_client, _cancel_tickers(
                    tickers
                ):
                    self.contextualise(web_client=web_client)
                    return await awaitable

            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(run())
            finally:
                loop.close()
