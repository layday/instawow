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
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, TypeVar
import urllib.parse

from loguru import logger
import sqlalchemy
import sqlalchemy.exc
import sqlalchemy.orm
from typing_extensions import Literal, TypeAlias, TypedDict
from yarl import URL

from . import _deferred_types, results as R
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
    _BaseResolverDict: TypeAlias = 'dict[str, Resolver]'
else:
    _BaseResolverDict = dict

_T = TypeVar('_T')
_C = TypeVar('_C', bound='Callable[..., Awaitable[object]]')


USER_AGENT = 'instawow (https://github.com/layday/instawow)'

DB_REVISION = '764fa963cc71'


class _GenericDownloadTraceRequestCtx(TypedDict):
    report_progress: Literal['generic']
    label: str


class _PkgDownloadTraceRequestCtx(TypedDict):
    report_progress: Literal['pkg_download']
    manager: Manager
    pkg: Pkg


TraceRequestCtx: TypeAlias = '_GenericDownloadTraceRequestCtx | _PkgDownloadTraceRequestCtx | None'


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
        logger.debug(f'{url} is cached at {dest}')
    elif url.startswith('file://'):
        await _copy_async(file_uri_to_path(url), dest)
    else:
        async with manager.web_client.get(
            url,
            raise_for_status=True,
            trace_request_ctx=_PkgDownloadTraceRequestCtx(
                report_progress='pkg_download', manager=manager, pkg=pkg
            ),
        ) as response, _open_temp_writer() as (temp_path, write):
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
        kwargs: dict[str, Any] = {
            'method': 'GET',
            'url': url,
            'raise_for_status': True,
            **request_extra,
        }
        if label:
            kwargs['trace_request_ctx'] = _GenericDownloadTraceRequestCtx(
                report_progress='generic', label=label
            )
        async with manager.web_client.request(**kwargs) as response:
            return await response.text()

    dest = manager.config.cache_dir / shasum(url, request_extra)
    if await t(is_not_stale)(dest, ttl):
        logger.debug(f'{url} is cache at {dest} (ttl: {ttl})')
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
    with engine.begin() as connection:
        try:
            current = connection.execute(
                sqlalchemy.text(
                    'SELECT version_num FROM alembic_version WHERE version_num = :version_num'
                ),
                {'version_num': DB_REVISION},
            ).scalar()
        except sqlalchemy.exc.OperationalError:
            return True
        else:
            return not current


def prepare_database(config: Config) -> sqlalchemy.orm.Session:
    from .models import ModelBase

    engine = sqlalchemy.create_engine(
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

            if sqlalchemy.inspect(engine).get_table_names():
                upgrade(alembic_config, DB_REVISION)
            else:
                ModelBase.metadata.create_all(engine)
                stamp(alembic_config, DB_REVISION)

    return sqlalchemy.orm.sessionmaker(bind=engine)()


def init_web_client(**kwargs: Any) -> _deferred_types.aiohttp.ClientSession:
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
    ) -> dict[Defn, Pkg | R.ManagerError | R.InternalError]:
        return dict.fromkeys(defns, R.PkgSourceInvalid())


class _ResolverDict(_BaseResolverDict):
    def __missing__(self, key: str) -> Resolver:
        return _DummyResolver


async def capture_manager_exc_async(
    awaitable: Awaitable[_T],
) -> _T | R.ManagerError | R.InternalError:
    "Capture and log an exception raised in a coroutine."
    from aiohttp import ClientError

    try:
        return await awaitable
    except (R.ManagerError, R.InternalError) as error:
        return error
    except ClientError as error:
        logger.opt(exception=True).info('network error')
        return R.InternalError(error)
    except BaseException as error:
        logger.exception('unclassed error')
        return R.InternalError(error)


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


_web_client: cv.ContextVar[_deferred_types.aiohttp.ClientSession] = cv.ContextVar('_web_client')

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
        web_client: _deferred_types.aiohttp.ClientSession | None = None,
        locks: defaultdict[str, asyncio.Lock] | None = None,
    ) -> None:
        if web_client is not None:
            _web_client.set(web_client)
        if locks is not None:
            _locks.set(locks)

    @classmethod
    def from_config(cls: type[_T], config: Config) -> _T:
        return cls(config, prepare_database(config))

    @property
    def web_client(self) -> _deferred_types.aiohttp.ClientSession:
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

        aliases_from_url = (
            (r.source, a)
            for r in self.resolvers.values()
            for a in (r.get_alias_from_url(value),)
            if a
        )
        return next(chain(aliases_from_url, from_urn(), (None,)))

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

    def install_pkg(self, pkg: Pkg, archive: Path, replace: bool) -> R.PkgInstalled:
        "Install a package."
        with _open_archive(archive) as (top_level_folders, extract):
            installed_conflicts: list[Pkg] = (
                self.database.query(Pkg)
                .join(Pkg.folders)
                .filter(PkgFolder.name.in_(top_level_folders))
                .all()
            )
            if installed_conflicts:
                raise R.PkgConflictsWithInstalled(installed_conflicts)

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
                    raise R.PkgConflictsWithUnreconciled(unreconciled_conflicts)

            extract(self.config.addon_dir)
            pkg.folders = [PkgFolder(name=f) for f in sorted(top_level_folders)]

        self.database.add(pkg)
        self.database.merge(
            PkgVersionLog(version=pkg.version, pkg_source=pkg.source, pkg_id=pkg.id)
        )
        self.database.commit()

        return R.PkgInstalled(pkg)

    def update_pkg(self, old_pkg: Pkg, new_pkg: Pkg, archive: Path) -> R.PkgUpdated:
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
                raise R.PkgConflictsWithInstalled(installed_conflicts)

            unreconciled_conflicts = top_level_folders - {f.name for f in old_pkg.folders} & {
                f.name for f in self.config.addon_dir.iterdir()
            }
            if unreconciled_conflicts:
                raise R.PkgConflictsWithUnreconciled(unreconciled_conflicts)

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

        return R.PkgUpdated(old_pkg, new_pkg)

    def remove_pkg(self, pkg: Pkg, keep_folders: bool) -> R.PkgRemoved:
        "Remove a package."
        if not keep_folders:
            trash(
                [self.config.addon_dir / f.name for f in pkg.folders],
                dest=self.config.temp_dir,
                missing_ok=True,
            )
        self.database.delete(pkg)
        self.database.commit()

        return R.PkgRemoved(pkg)

    @_with_lock('load catalogue', False)
    async def synchronise(self) -> Catalogue:
        "Fetch the catalogue from the interwebs and load it."
        if self._catalogue is None:
            label = 'Synchronising catalogue'
            url = (
                'https://raw.githubusercontent.com/layday/instawow-data/data/'
                'master-catalogue-v4.compact.json'
            )  # v4
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

    async def get_changelog(self, uri: str) -> str:
        "Retrieve a changelog from its URL."
        url = URL(uri)
        if url.scheme == 'data' and url.raw_path.startswith(','):
            return urllib.parse.unquote(url.raw_path[1:])
        elif url.scheme in {'http', 'https'}:
            return await cache_response(
                self,
                url,
                {'days': 1},
                is_json=False,
            )
        elif url.scheme == 'file':
            return await t(Path(file_uri_to_path(uri)).read_text)(encoding='utf-8')
        else:
            raise ValueError('Unsupported URL with scheme', url.scheme)

    async def search(
        self,
        search_terms: str,
        limit: int,
        sources: Set[str] | None = None,
    ) -> list[CatalogueEntry]:
        "Search the master catalogue for packages by name."
        import rapidfuzz

        catalogue = await self.synchronise()

        w = 0.5  # Weighing edit distance and download score equally
        normalise = normalise_names('')

        if sources is None:
            sources = self.resolvers.keys()

        s = normalise(search_terms)
        tokens_to_entries = bucketise(
            (
                (normalise(i.name), i)
                for i in catalogue.__root__
                if self.config.game_flavour in i.game_flavours and i.source in sources
            ),
            key=lambda v: v[0],
        )
        matches: list[tuple[str, float, int]] = rapidfuzz.process.extract(
            s, list(tokens_to_entries), scorer=rapidfuzz.fuzz.WRatio, limit=limit
        )
        weighted_entries = sorted(
            (
                (-((s / 100) * w + i.derived_download_score * (1 - w)), i)
                for m, s, _ in matches
                for _, i in tokens_to_entries[m]
            ),
            key=lambda v: v[0],
        )
        return [e for _, e in weighted_entries]

    @_with_lock('change state')
    async def install(
        self, defns: Sequence[Defn], replace: bool
    ) -> dict[Defn, R.PkgInstalled | R.ManagerError | R.InternalError]:
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
        installables = {d: r for d, r in resolve_results.items() if is_pkg(r)}
        archives = await gather(
            (_download_archive(self, r) for r in installables.values()), capture_manager_exc_async
        )
        results = chain_dict(
            defns,
            R.PkgAlreadyInstalled(),
            resolve_results.items(),
            ((d, a) for d, a in zip(installables, archives) if not isinstance(a, PurePath)),
            [
                (d, await capture_manager_exc_async(t(self.install_pkg)(p, a, replace)))
                for (d, p), a in zip(installables.items(), archives)
                if isinstance(a, PurePath)
            ],
        )
        return results

    @_with_lock('change state')
    async def update(
        self, defns: Sequence[Defn], retain_strategy: bool
    ) -> dict[Defn, R.PkgUpdated | R.ManagerError | R.InternalError]:
        """Update installed packages from a definition list.

        A ``retain_strategy`` value of false will instruct ``update``
        to extract the strategy from the installed package; otherwise
        the ``Defn`` strategy will be used.
        """
        defns_to_pkgs = {d: p for d in defns for p in (self.get_pkg(d),) if p}
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
            d: (o, n)
            for d, n in installables.items()
            for o in (defns_to_pkgs[d],)
            if n.version != o.version
        }
        archives = await gather(
            (_download_archive(self, n) for _, n in updatables.values()), capture_manager_exc_async
        )
        results = chain_dict(
            defns,
            R.PkgNotInstalled(),
            resolve_results.items(),
            (
                (d, R.PkgUpToDate(is_pinned=p.options.strategy == Strategy.version))
                for d, p in installables.items()
            ),
            ((d, a) for d, a in zip(updatables, archives) if not isinstance(a, PurePath)),
            [
                (d, await capture_manager_exc_async(t(self.update_pkg)(o, n, a)))
                for (d, (o, n)), a in zip(updatables.items(), archives)
                if isinstance(a, PurePath)
            ],
        )
        return results

    @_with_lock('change state')
    async def remove(
        self, defns: Sequence[Defn], keep_folders: bool
    ) -> dict[Defn, R.PkgRemoved | R.ManagerError | R.InternalError]:
        "Remove packages by their definition."
        results = chain_dict(
            defns,
            R.PkgNotInstalled(),
            [
                (d, await capture_manager_exc_async(t(self.remove_pkg)(p, keep_folders)))
                for d in defns
                for p in (self.get_pkg(d),)
                if p
            ],
        )
        return results

    @_with_lock('change state')
    async def pin(
        self, defns: Sequence[Defn]
    ) -> dict[
        Defn,
        R.PkgNotInstalled
        | R.PkgInstalled
        | R.PkgStrategyUnsupported
        | R.ManagerError
        | R.InternalError,
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
        ) -> R.PkgNotInstalled | R.PkgInstalled | R.PkgStrategyUnsupported:
            if not pkg:
                return R.PkgNotInstalled()
            elif {defn.strategy} <= strategies <= self.resolvers[pkg.source].strategies:
                pkg.options.strategy = defn.strategy
                self.database.commit()
                return R.PkgInstalled(pkg)
            else:
                return R.PkgStrategyUnsupported(Strategy.version)

        return {d: await capture_manager_exc_async(t(pin)(d, self.get_pkg(d))) for d in defns}


def _extract_filename_from_hdr(response: _deferred_types.aiohttp.ClientResponse) -> str:
    from cgi import parse_header

    from aiohttp import hdrs

    _, cd_params = parse_header(response.headers.get(hdrs.CONTENT_DISPOSITION, ''))
    filename = cd_params.get('filename') or response.url.name
    return filename


def _init_cli_web_client(
    bar: _deferred_types.prompt_toolkit.shortcuts.ProgressBar, tickers: set[asyncio.Task[None]]
) -> _deferred_types.aiohttp.ClientSession:
    from aiohttp import TraceConfig, TraceRequestEndParams, hdrs

    TICK_INTERVAL = 0.1

    async def do_on_request_end(
        client_session: _deferred_types.aiohttp.ClientSession,
        trace_config_ctx: SimpleNamespace,
        params: TraceRequestEndParams,
    ) -> None:
        trace_request_ctx: TraceRequestCtx = trace_config_ctx.trace_request_ctx
        if trace_request_ctx:
            response = params.response
            label = (
                trace_request_ctx.get('label')
                or f'Downloading {_extract_filename_from_hdr(response)}'
            )
            total = response.content_length
            if hdrs.CONTENT_ENCODING in response.headers:
                # The encoded size is not exposed in the aiohttp streaming API.
                # If the payload is encoded, ``total`` is set to ``None``
                # for the progress bar to be rendered as indeterminate.
                total = None

            async def ticker() -> None:
                counter = bar(label=label, total=total)
                try:
                    while not response.content.is_eof():
                        counter.items_completed = response.content.total_bytes
                        bar.invalidate()
                        await asyncio.sleep(TICK_INTERVAL)
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
                tickers: set[asyncio.Task[None]] = set()
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
