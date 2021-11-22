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
from datetime import datetime
from enum import IntEnum
from functools import lru_cache, partial, wraps
from itertools import chain, compress, filterfalse, repeat, starmap, takewhile
import json
from pathlib import Path, PurePath
from shutil import copy
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, TypeVar
import urllib.parse

from loguru import logger
import sqlalchemy as sa
import sqlalchemy.exc as sa_exc
import sqlalchemy.future as sa_future
from typing_extensions import Concatenate, Literal, ParamSpec, TypeAlias, TypedDict
from yarl import URL

from . import _deferred_types, db, models
from . import results as R
from .cataloguer import Catalogue, CatalogueEntry
from .common import Strategy
from .config import Config
from .plugins import load_plugins
from .resolvers import (
    BaseResolver,
    CurseResolver,
    Defn,
    GithubResolver,
    InstawowResolver,
    Resolver,
    TukuiResolver,
    WowiResolver,
)
from .utils import (
    bucketise,
    chain_dict,
    file_uri_to_path,
    find_addon_zip_base_dirs,
    gather,
    is_not_stale,
    make_zip_member_filter,
    move,
    normalise_names,
)
from .utils import run_in_thread as t
from .utils import shasum, trash, uniq

if TYPE_CHECKING:  # pragma: no cover
    _BaseResolverDict: TypeAlias = 'dict[str, Resolver]'
else:
    _BaseResolverDict = dict

_P = ParamSpec('_P')
_T = TypeVar('_T')
_CManager: TypeAlias = 'Callable[Concatenate[Manager, _P], Awaitable[_T]]'


USER_AGENT = 'instawow (https://github.com/layday/instawow)'

DB_REVISION = '75f69831f74f'


class _GenericDownloadTraceRequestCtx(TypedDict):
    report_progress: Literal['generic']
    label: str


class _PkgDownloadTraceRequestCtx(TypedDict):
    report_progress: Literal['pkg_download']
    manager: Manager
    pkg: models.Pkg


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
def _open_pkg_archive(path: PurePath) -> Iterator[tuple[set[str], Callable[[Path], None]]]:
    from zipfile import ZipFile

    with ZipFile(path) as archive:

        def extract(parent: Path) -> None:
            archive.extractall(parent, members=filter(make_zip_member_filter(base_dirs), names))

        names = archive.namelist()
        base_dirs = set(find_addon_zip_base_dirs(names))
        yield (base_dirs, extract)


async def _download_pkg_archive(
    manager: Manager, pkg: models.Pkg, *, chunk_size: int = 4096
) -> Path:
    url = pkg.download_url
    dest = manager.config.global_config.cache_dir / shasum(
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

    dest = manager.config.global_config.cache_dir / shasum(url, request_extra)
    if await t(is_not_stale)(dest, ttl):
        logger.debug(f'{url} is cached at {dest} (ttl: {ttl})')
        text = await t(dest.read_text)(encoding='utf-8')
    else:
        text = await make_request()
        await t(dest.write_text)(text, encoding='utf-8')

    return json.loads(text) if is_json else text


class DatabaseState(IntEnum):
    current = 0
    old = 1
    uninitialised = 2


def get_database_state(engine: sa_future.Engine) -> DatabaseState:
    with engine.connect() as connection:
        try:
            state = connection.execute(
                sa.text(
                    'SELECT ifnull((SELECT 0 FROM alembic_version WHERE version_num == :version_num), 1)',
                ),
                {'version_num': DB_REVISION},
            ).scalar()
        except sa_exc.OperationalError:
            state = connection.execute(
                sa.text(
                    'SELECT ifnull((SELECT 1 FROM sqlite_master WHERE type = "table" LIMIT 1), 2)',
                )
            ).scalar()

    return DatabaseState(state)


def migrate_database(engine: sa_future.Engine) -> None:
    should_migrate = get_database_state(engine)
    if should_migrate != DatabaseState.current:
        import alembic.command
        import alembic.config

        alembic_config = alembic.config.Config()
        alembic_config.set_main_option('script_location', f'{__package__}:migrations')
        alembic_config.set_main_option('sqlalchemy.url', str(engine.url))

        if should_migrate == DatabaseState.uninitialised:
            db.metadata.create_all(engine)
            alembic.command.stamp(alembic_config, DB_REVISION)
        else:
            alembic.command.upgrade(alembic_config, DB_REVISION)


def prepare_database(config: Config) -> sa_future.Engine:
    engine = sa.create_engine(
        f'sqlite:///{config.db_file}',
        # We wanna be able to operate on the database from executor threads
        # when performing disk I/O
        connect_args={'check_same_thread': False},
        # echo=True,
        future=True,
    )
    migrate_database(engine)
    return engine


@lru_cache(None)
def _load_certifi_certs():
    try:
        import certifi
    except ModuleNotFoundError:
        pass
    else:
        from importlib.resources import read_text

        logger.info('loading certifi certs')
        return read_text(certifi, 'cacert.pem', encoding='ascii')


def init_web_client(**kwargs: Any) -> _deferred_types.aiohttp.ClientSession:
    from aiohttp import ClientSession, ClientTimeout, TCPConnector

    make_connector = partial(TCPConnector, force_close=True, limit_per_host=10)
    certifi_certs = _load_certifi_certs()
    if certifi_certs:
        import ssl

        make_connector = partial(
            make_connector, ssl=ssl.create_default_context(cadata=certifi_certs)
        )

    kwargs = {
        'connector': make_connector(),
        'headers': {'User-Agent': USER_AGENT},
        'trust_env': True,  # Respect the 'http_proxy' env var
        'timeout': ClientTimeout(connect=60, sock_connect=10, sock_read=10),
        **kwargs,
    }
    return ClientSession(**kwargs)


@object.__new__
class _DummyResolver(BaseResolver):
    strategies = frozenset()

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
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
):
    def outer(coro_fn: _CManager[_P, _T]) -> _CManager[_P, _T]:
        @wraps(coro_fn)
        async def inner(self: Manager, *args: _P.args, **kwargs: _P.kwargs):
            async with self.locks[f'{id(self)}-{lock_name}' if manager_bound else lock_name]:
                return await coro_fn(self, *args, **kwargs)

        return inner

    return outer


_web_client: cv.ContextVar[_deferred_types.aiohttp.ClientSession] = cv.ContextVar('_web_client')

_dummy_locks: defaultdict[str, Any] = defaultdict(_DummyLock)
_locks: cv.ContextVar[defaultdict[str, asyncio.Lock]] = cv.ContextVar(
    '_locks', default=_dummy_locks
)


class Manager:
    RESOLVERS = [
        CurseResolver,
        WowiResolver,
        TukuiResolver,
        GithubResolver,
        InstawowResolver,
    ]

    _catalogue_url = 'https://raw.githubusercontent.com/layday/instawow-data/data/base-catalogue-v5.compact.json'  # v5
    _catalogue_filename = 'catalogue.json'

    _normalise_search_terms = staticmethod(normalise_names(''))

    def __init__(
        self,
        config: Config,
        database: sa_future.Connection,
    ) -> None:
        self.config: Config = config
        self.database: sa_future.Connection = database

        plugin_hook = load_plugins()
        resolver_classes = chain(
            (r for g in plugin_hook.instawow_add_resolvers() for r in g), self.RESOLVERS
        )
        self.resolvers: _ResolverDict = _ResolverDict(
            (r.source, r(self)) for r in resolver_classes
        )

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
    def from_config(cls, config: Config) -> Manager:
        return cls(config, prepare_database(config).connect())

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
            for a in (r.get_alias_from_url(URL(value)),)
            if a
        )
        return next(chain(aliases_from_url, from_urn(), (None,)))

    def check_pkg_exists(self, defn: Defn) -> bool:
        return (
            self.database.execute(
                sa.select(sa.func.count())
                .select_from(db.pkg)
                .filter(
                    db.pkg.c.source == defn.source,
                    (db.pkg.c.id == defn.alias)
                    | (db.pkg.c.id == defn.id)
                    | (db.pkg.c.slug == defn.alias),
                )
            ).scalar()
            != 0
        )

    def get_pkg(self, defn: Defn, partial_match: bool = False) -> models.Pkg | None:
        "Retrieve an installed package from a definition."
        maybe_row_mapping = (
            self.database.execute(
                sa.select(db.pkg).filter(
                    db.pkg.c.source == defn.source,
                    (db.pkg.c.id == defn.alias)
                    | (db.pkg.c.id == defn.id)
                    | (db.pkg.c.slug == defn.alias),
                )
            )
            .mappings()
            .one_or_none()
        )
        if maybe_row_mapping is None and partial_match:
            maybe_row_mapping = (
                self.database.execute(
                    sa.select(db.pkg)
                    .filter(db.pkg.c.slug.contains(defn.alias))
                    .order_by(db.pkg.c.name)
                )
                .mappings()
                .first()
            )
        if maybe_row_mapping is not None:
            return models.Pkg.from_row_mapping(self.database, maybe_row_mapping)

    def install_pkg(self, pkg: models.Pkg, archive: Path, replace: bool) -> R.PkgInstalled:
        "Install a package."
        with _open_pkg_archive(archive) as (top_level_folders, extract):
            installed_conflicts = self.database.execute(
                sa.select(db.pkg)
                .distinct()
                .join(db.pkg_folder)
                .filter(db.pkg_folder.c.name.in_(top_level_folders))
            ).all()
            if installed_conflicts:
                raise R.PkgConflictsWithInstalled(installed_conflicts)

            if replace:
                trash(
                    [self.config.addon_dir / f for f in top_level_folders],
                    dest=self.config.global_config.temp_dir,
                    missing_ok=True,
                )
            else:
                unreconciled_conflicts = top_level_folders & {
                    f.name for f in self.config.addon_dir.iterdir()
                }
                if unreconciled_conflicts:
                    raise R.PkgConflictsWithUnreconciled(unreconciled_conflicts)

            extract(self.config.addon_dir)

        pkg = models.Pkg.parse_obj(
            {**pkg.__dict__, 'folders': [{'name': f} for f in sorted(top_level_folders)]}
        )
        pkg.insert(self.database)
        return R.PkgInstalled(pkg)

    def update_pkg(self, pkg1: models.Pkg, pkg2: models.Pkg, archive: Path) -> R.PkgUpdated:
        "Update a package."
        with _open_pkg_archive(archive) as (top_level_folders, extract):
            installed_conflicts = self.database.execute(
                sa.select(db.pkg)
                .distinct()
                .join(db.pkg_folder)
                .filter(
                    db.pkg_folder.c.pkg_source != pkg2.source,
                    db.pkg_folder.c.pkg_id != pkg2.id,
                    db.pkg_folder.c.name.in_(top_level_folders),
                )
            ).all()
            if installed_conflicts:
                raise R.PkgConflictsWithInstalled(installed_conflicts)

            unreconciled_conflicts = top_level_folders - {f.name for f in pkg1.folders} & {
                f.name for f in self.config.addon_dir.iterdir()
            }
            if unreconciled_conflicts:
                raise R.PkgConflictsWithUnreconciled(unreconciled_conflicts)

            trash(
                [self.config.addon_dir / f.name for f in pkg1.folders],
                dest=self.config.global_config.temp_dir,
                missing_ok=True,
            )
            extract(self.config.addon_dir)

        pkg2 = models.Pkg.parse_obj(
            {**pkg2.__dict__, 'folders': [{'name': f} for f in sorted(top_level_folders)]}
        )
        pkg1.delete(self.database)
        pkg2.insert(self.database)
        return R.PkgUpdated(pkg1, pkg2)

    def remove_pkg(self, pkg: models.Pkg, keep_folders: bool) -> R.PkgRemoved:
        "Remove a package."
        if not keep_folders:
            trash(
                [self.config.addon_dir / f.name for f in pkg.folders],
                dest=self.config.global_config.temp_dir,
                missing_ok=True,
            )

        pkg.delete(self.database)
        return R.PkgRemoved(pkg)

    @_with_lock('load catalogue', False)
    async def synchronise(self) -> Catalogue:
        "Fetch the catalogue from the interwebs and load it."
        catalogue_json = self.config.global_config.temp_dir / self._catalogue_filename
        if await t(is_not_stale)(catalogue_json, {'hours': 4}):
            if self._catalogue is None:
                self._catalogue = Catalogue.parse_raw(
                    await t(catalogue_json.read_text)(encoding='utf-8')
                )
        else:
            async with self.web_client.get(
                self._catalogue_url,
                trace_request_ctx=_GenericDownloadTraceRequestCtx(
                    report_progress='generic', label='Synchronising catalogue'
                ),
            ) as response:
                raw_catalogue = await response.json(content_type=None)

            self._catalogue = Catalogue.from_base_catalogue(raw_catalogue, None)
            await t(catalogue_json.write_text)(self._catalogue.json(), encoding='utf-8')

        return self._catalogue

    async def _resolve_deps(self, results: Iterable[Any]) -> dict[Defn, Any]:
        """Resolve package dependencies.

        The resolver will not follow dependencies
        more than one level deep.  This is to avoid unnecessary
        complexity for something that I would never expect to
        encounter in the wild.
        """
        pkgs = [r for r in results if models.is_pkg(r)]
        dep_defns = uniq(
            filterfalse(
                {(p.source, p.id) for p in pkgs}.__contains__,
                ((p.source, d.id) for p in pkgs for d in p.deps),
            )
        )
        if not dep_defns:
            return {}

        deps = await self.resolve(list(starmap(Defn, dep_defns)))
        pretty_deps = {
            d.with_(alias=r.slug) if models.is_pkg(r) else d: r for d, r in deps.items()
        }
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
        sources: Set[str] = frozenset(),
        start_date: datetime | None = None,
    ) -> list[CatalogueEntry]:
        "Search the master catalogue for packages by name."
        import rapidfuzz

        catalogue = await self.synchronise()

        ew = 0.5
        dw = 1 - ew

        if not sources:
            sources = self.resolvers.keys()
        else:
            unknown_sources = sources - self.resolvers.keys()
            if unknown_sources:
                raise ValueError(f'Unknown sources: {", ".join(unknown_sources)}')

        def make_filter():
            def filter_game_flavour(entry: CatalogueEntry):
                return self.config.game_flavour in entry.game_flavours

            yield filter_game_flavour

            if sources is not None:

                def filter_sources(entry: CatalogueEntry):
                    return entry.source in sources

                yield filter_sources

            if start_date is not None:
                start_date_ = start_date

                def filter_age(entry: CatalogueEntry):
                    return entry.last_updated >= start_date_

                yield filter_age

        filter_fns = list(make_filter())

        s = self._normalise_search_terms(search_terms)

        tokens_to_entries = bucketise(
            ((e.normalised_name, e) for e in catalogue.__root__ if all(f(e) for f in filter_fns)),
            key=lambda v: v[0],
        )
        matches = rapidfuzz.process.extract(
            s, list(tokens_to_entries), scorer=rapidfuzz.fuzz.WRatio, limit=limit * 2
        )
        weighted_entries = sorted(
            (
                (-((s / 100) * ew + e.derived_download_score * dw), e)
                for m, s, _ in matches
                for _, e in tokens_to_entries[m]
            ),
            key=lambda v: v[0],
        )
        return [e for _, e in weighted_entries[:limit]]

    @_with_lock('change state')
    async def install(
        self, defns: Sequence[Defn], replace: bool
    ) -> dict[Defn, R.PkgInstalled | R.ManagerError | R.InternalError]:
        "Install packages from a definition list."
        # We'll weed out installed deps from the results after resolving -
        # doing it this way isn't particularly efficient but avoids having to
        # deal with local state in `resolve()`
        resolve_results = await self.resolve(
            list(compress(defns, (not self.check_pkg_exists(d) for d in defns))),
            with_deps=True,
        )
        resolve_results = dict(
            compress(
                resolve_results.items(), (not self.check_pkg_exists(d) for d in resolve_results)
            )
        )
        installables = {d: r for d, r in resolve_results.items() if models.is_pkg(r)}
        archives = await gather(
            (_download_pkg_archive(self, r) for r in installables.values()),
            capture_manager_exc_async,
        )
        results = chain_dict(
            defns,
            R.PkgAlreadyInstalled(),
            resolve_results.items(),
            [
                (d, await capture_manager_exc_async(t(self.install_pkg)(p, a, replace)))
                if isinstance(a, PurePath)
                else (d, a)
                for (d, p), a in zip(installables.items(), archives)
            ],
        )
        return results

    @_with_lock('change state')
    async def update(
        self, defns: Sequence[Defn], retain_defn_strategy: bool
    ) -> dict[Defn, R.PkgUpdated | R.ManagerError | R.InternalError]:
        """Update installed packages from a definition list.

        A ``retain_defn_strategy`` value of false will instruct ``update``
        to extract the strategy from the installed package; otherwise
        the ``Defn`` strategy will be used.
        """
        defns_to_pkgs = {d: p for d in defns for p in (self.get_pkg(d),) if p}
        resolve_defns = {
            # Attach the source ID to each ``Defn`` from the
            # corresponding installed package.  Using the ID has the benefit
            # of resolving installed-but-renamed packages - the slug is
            # transient but the ID isn't
            d.with_(id=p.id) if retain_defn_strategy else Defn.from_pkg(p): d
            for d, p in defns_to_pkgs.items()
        }
        # Discard the reconstructed ``Defn``s
        resolve_results = {
            resolve_defns[d]: r for d, r in (await self.resolve(list(resolve_defns))).items()
        }
        installables = {d: r for d, r in resolve_results.items() if models.is_pkg(r)}
        updatables = {
            d: (o, n)
            for d, n in installables.items()
            for o in (defns_to_pkgs[d],)
            if n.version != o.version
        }
        archives = await gather(
            (_download_pkg_archive(self, n) for _, n in updatables.values()),
            capture_manager_exc_async,
        )
        results = chain_dict(
            defns,
            R.PkgNotInstalled(),
            resolve_results.items(),
            (
                (d, R.PkgUpToDate(is_pinned=p.options.strategy == Strategy.version))
                for d, p in installables.items()
            ),
            [
                (d, await capture_manager_exc_async(t(self.update_pkg)(o, n, a)))
                if isinstance(a, PurePath)
                else (d, a)
                for (d, (o, n)), a in zip(updatables.items(), archives)
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

        def pin(defn: Defn, pkg: models.Pkg | None) -> R.PkgInstalled:
            if not pkg:
                raise R.PkgNotInstalled

            elif {defn.strategy} <= strategies <= self.resolvers[pkg.source].strategies:
                self.database.execute(
                    sa.update(db.pkg_options)
                    .filter_by(pkg_source=pkg.source, pkg_id=pkg.id)
                    .values(strategy=defn.strategy)
                )
                self.database.commit()
                row_mapping = (
                    self.database.execute(
                        sa.select(db.pkg).filter_by(source=pkg.source, id=pkg.id)
                    )
                    .mappings()
                    .one()
                )
                return R.PkgInstalled(models.Pkg.from_row_mapping(self.database, row_mapping))

            else:
                raise R.PkgStrategyUnsupported(Strategy.version)

        return {d: await capture_manager_exc_async(t(pin)(d, self.get_pkg(d))) for d in defns}


async def is_outdated() -> tuple[bool, str]:
    """Check on PyPI to see if the installed copy of instawow is outdated.

    The response is cached for 24 hours.
    """
    from aiohttp.client import ClientError

    from . import __version__

    def parse_version(version: str):
        version_parts = takewhile(lambda p: all(c in '0123456789' for c in p), version.split('.'))
        return tuple(map(int, version_parts))

    if __version__ == '0.0.0':
        return (False, '')

    dummy_config = Config.get_dummy_config()
    if not dummy_config.global_config.auto_update_check:
        return (False, '')

    cache_file = dummy_config.global_config.temp_dir / '.pypi_version'
    if await t(is_not_stale)(cache_file, {'days': 1}):
        version = cache_file.read_text(encoding='utf-8')
    else:
        try:
            async with init_web_client(raise_for_status=True) as web_client, web_client.get(
                'https://pypi.org/pypi/instawow/json'
            ) as response:
                version = (await response.json())['info']['version']
        except ClientError:
            version = __version__
        else:
            cache_file.write_text(version, encoding='utf-8')

    return (parse_version(version) > parse_version(__version__), version)
