from __future__ import annotations

import datetime as dt
from collections.abc import (
    Awaitable,
    Callable,
    Collection,
    Iterable,
    Mapping,
    Sequence,
)
from contextlib import asynccontextmanager
from functools import lru_cache, wraps
from itertools import filterfalse, product, repeat, starmap
from pathlib import Path
from shutil import move
from tempfile import NamedTemporaryFile
from typing import Concatenate, TypeVar

import sqlalchemy as sa
from attrs import asdict, evolve
from cattrs import Converter
from loguru import logger
from typing_extensions import Never, ParamSpec
from yarl import URL

from . import pkg_db, pkg_models
from . import results as R
from .common import Defn, Strategy
from .http import CACHE_INDEFINITELY, make_defn_progress_ctx
from .manager_ctx import ManagerCtx
from .resolvers import HeadersIntent
from .utils import (
    bucketise,
    chain_dict,
    file_uri_to_path,
    gather,
    is_file_uri,
    run_in_thread,
    shasum,
    time_op,
    trash,
    uniq,
)

_P = ParamSpec('_P')
_T = TypeVar('_T')
_TPkgManager = TypeVar('_TPkgManager', bound='PkgManager')

_AsyncNamedTemporaryFile = run_in_thread(NamedTemporaryFile)
_move_async = run_in_thread(move)

_MUTATE_PKGS_LOCK = '_MUTATE_PKGS_'
_DOWNLOAD_PKG_LOCK = '_DOWNLOAD_PKG_'


@lru_cache(1)
def _make_db_pkg_converter():
    converter = Converter()
    converter.register_structure_hook(dt.datetime, lambda d, _: d)
    return converter


def bucketise_results(
    values: Iterable[tuple[Defn, R.AnyResult[_T]]],
):
    ts: dict[Defn, _T] = {}
    errors: dict[Defn, R.AnyResult[Never]] = {}

    for defn, value in values:
        if isinstance(value, R.ManagerError | R.InternalError):
            errors[defn] = value
        else:
            ts[defn] = value

    return ts, errors


@asynccontextmanager
async def _open_temp_writer_async():
    fh = await _AsyncNamedTemporaryFile(delete=False)
    path = Path(fh.name)
    try:
        yield (path, run_in_thread(fh.write))
    except BaseException:
        await run_in_thread(fh.close)()
        await run_in_thread(path.unlink)()
        raise
    else:
        await run_in_thread(fh.close)()


async def _download_pkg_archive(ctx: ManagerCtx, defn: Defn, pkg: pkg_models.Pkg):
    if is_file_uri(pkg.download_url):
        return Path(file_uri_to_path(pkg.download_url))

    async with ctx.locks[_DOWNLOAD_PKG_LOCK, pkg.download_url]:
        headers = await ctx.resolvers[pkg.source].make_request_headers(
            intent=HeadersIntent.Download
        )
        trace_request_ctx = make_defn_progress_ctx(ctx.config.profile, defn)

        async with (
            ctx.web_client.get(
                pkg.download_url,
                headers=headers,
                raise_for_status=True,
                trace_request_ctx=trace_request_ctx,
                expire_after=CACHE_INDEFINITELY,
            ) as response,
            _open_temp_writer_async() as (temp_path, write),
        ):
            async for chunk, _ in response.content.iter_chunks():
                await write(chunk)

        return await _move_async(
            temp_path,
            ctx.config.global_config.install_cache_dir / shasum(pkg.download_url),
        )


def _insert_db_pkg(pkg: pkg_models.Pkg, transaction: sa.Connection):
    values = asdict(pkg)
    source_and_id = {'pkg_source': values['source'], 'pkg_id': values['id']}

    transaction.execute(sa.insert(pkg_db.pkg), [values])
    transaction.execute(
        sa.insert(pkg_db.pkg_folder), [{**f, **source_and_id} for f in values['folders']]
    )
    transaction.execute(sa.insert(pkg_db.pkg_options), [{**values['options'], **source_and_id}])
    if values['deps']:
        transaction.execute(
            sa.insert(pkg_db.pkg_dep), [{**d, **source_and_id} for d in values['deps']]
        )
    transaction.execute(
        sa.insert(pkg_db.pkg_version_log).prefix_with('OR IGNORE'),
        [{'version': values['version'], **source_and_id}],
    )


def _delete_db_pkg(pkg: pkg_models.Pkg, transaction: sa.Connection):
    transaction.execute(sa.delete(pkg_db.pkg).filter_by(source=pkg.source, id=pkg.id))


@run_in_thread
def _install_pkg(
    ctx: ManagerCtx, pkg: pkg_models.Pkg, archive: Path, replace_folders: bool
) -> R.PkgInstalled:
    with ctx.resolvers.archive_opener_dict[pkg.source](archive) as (top_level_folders, extract):
        with ctx.database.connect() as connection:
            installed_conflicts = connection.execute(
                sa.select(pkg_db.pkg)
                .distinct()
                .join(pkg_db.pkg_folder)
                .where(pkg_db.pkg_folder.c.name.in_(top_level_folders))
            ).all()
        if installed_conflicts:
            raise R.PkgConflictsWithInstalled(installed_conflicts)

        if replace_folders:
            trash(
                (ctx.config.addon_dir / f for f in top_level_folders),
                dest=ctx.config.global_config.temp_dir,
                missing_ok=True,
            )
        else:
            unreconciled_conflicts = top_level_folders & {
                f.name for f in ctx.config.addon_dir.iterdir()
            }
            if unreconciled_conflicts:
                raise R.PkgConflictsWithUnreconciled(unreconciled_conflicts)

        extract(ctx.config.addon_dir)

    pkg = evolve(pkg, folders=[pkg_models.PkgFolder(name=f) for f in sorted(top_level_folders)])
    with ctx.database.begin() as transaction:
        _insert_db_pkg(pkg, transaction)

    return R.PkgInstalled(pkg)


@run_in_thread
def _update_pkg(
    ctx: ManagerCtx, old_pkg: pkg_models.Pkg, new_pkg: pkg_models.Pkg, archive: Path
) -> R.PkgUpdated:
    with ctx.resolvers.archive_opener_dict[new_pkg.source](archive) as (
        top_level_folders,
        extract,
    ):
        with ctx.database.connect() as connection:
            installed_conflicts = connection.execute(
                sa.select(pkg_db.pkg)
                .distinct()
                .join(pkg_db.pkg_folder)
                .where(
                    pkg_db.pkg_folder.c.pkg_source != new_pkg.source,
                    pkg_db.pkg_folder.c.pkg_id != new_pkg.id,
                    pkg_db.pkg_folder.c.name.in_(top_level_folders),
                )
            ).all()
        if installed_conflicts:
            raise R.PkgConflictsWithInstalled(installed_conflicts)

        unreconciled_conflicts = top_level_folders - {f.name for f in old_pkg.folders} & {
            f.name for f in ctx.config.addon_dir.iterdir()
        }
        if unreconciled_conflicts:
            raise R.PkgConflictsWithUnreconciled(unreconciled_conflicts)

        trash(
            (ctx.config.addon_dir / f.name for f in old_pkg.folders),
            dest=ctx.config.global_config.temp_dir,
            missing_ok=True,
        )
        extract(ctx.config.addon_dir)

    new_pkg = evolve(
        new_pkg, folders=[pkg_models.PkgFolder(name=f) for f in sorted(top_level_folders)]
    )
    with ctx.database.begin() as transaction:
        _delete_db_pkg(old_pkg, transaction)
        _insert_db_pkg(new_pkg, transaction)

    return R.PkgUpdated(old_pkg, new_pkg)


@run_in_thread
def _remove_pkg(ctx: ManagerCtx, pkg: pkg_models.Pkg, keep_folders: bool) -> R.PkgRemoved:
    if not keep_folders:
        trash(
            (ctx.config.addon_dir / f.name for f in pkg.folders),
            dest=ctx.config.global_config.temp_dir,
            missing_ok=True,
        )

    with ctx.database.begin() as transaction:
        _delete_db_pkg(pkg, transaction)

    return R.PkgRemoved(pkg)


@object.__new__
class _DummyResolver:
    async def resolve(self, defns: Sequence[Defn]) -> dict[Defn, R.AnyResult[pkg_models.Pkg]]:
        return dict.fromkeys(defns, R.PkgSourceInvalid())

    async def get_changelog(self, uri: URL) -> str:
        raise R.PkgSourceInvalid


def _with_lock(lock_name: str):
    def outer(
        coro_fn: Callable[Concatenate[_TPkgManager, _P], Awaitable[_T]],
    ) -> Callable[Concatenate[_TPkgManager, _P], Awaitable[_T]]:
        @wraps(coro_fn)
        async def inner(self: _TPkgManager, *args: _P.args, **kwargs: _P.kwargs) -> _T:
            async with self.ctx.locks[lock_name, id(self)]:
                return await coro_fn(self, *args, **kwargs)

        return inner

    return outer


class PkgManager:
    def __init__(self, ctx: ManagerCtx) -> None:
        self.ctx = ctx

    def pair_uri(self, value: str) -> tuple[str, str] | None:
        "Attempt to extract a valid ``Defn`` source and alias from a URL."
        aliases_from_url = (
            (r.metadata.id, a)
            for r in self.ctx.resolvers.values()
            for a in (r.get_alias_from_url(URL(value)),)
            if a
        )
        return next(aliases_from_url, None)

    def check_pkg_exists(self, defn: Defn) -> bool:
        "Check that a package exists in the database."
        with self.ctx.database.connect() as connection:
            return (
                connection.execute(
                    sa.select(sa.text('1'))
                    .select_from(pkg_db.pkg)
                    .where(
                        pkg_db.pkg.c.source == defn.source,
                        (pkg_db.pkg.c.id == defn.alias)
                        | (pkg_db.pkg.c.id == defn.id)
                        | (sa.func.lower(pkg_db.pkg.c.slug) == sa.func.lower(defn.alias)),
                    )
                ).scalar()
                == 1
            )

    def get_pkg(self, defn: Defn, partial_match: bool = False) -> pkg_models.Pkg | None:
        "Retrieve a package from the database."
        with self.ctx.database.connect() as connection:
            maybe_row_mapping = (
                connection.execute(
                    sa.select(pkg_db.pkg).where(
                        pkg_db.pkg.c.source == defn.source,
                        (pkg_db.pkg.c.id == defn.alias)
                        | (pkg_db.pkg.c.id == defn.id)
                        | (sa.func.lower(pkg_db.pkg.c.slug) == sa.func.lower(defn.alias)),
                    )
                )
                .mappings()
                .one_or_none()
            )
            if maybe_row_mapping is None and partial_match:
                maybe_row_mapping = (
                    connection.execute(
                        sa.select(pkg_db.pkg)
                        .where(pkg_db.pkg.c.slug.contains(defn.alias))
                        .order_by(pkg_db.pkg.c.name)
                    )
                    .mappings()
                    .first()
                )
            if maybe_row_mapping is not None:
                return self.build_pkg_from_row_mapping(connection, maybe_row_mapping)

    def build_pkg_from_row_mapping(
        self, connection: sa.Connection, row_mapping: sa.RowMapping
    ) -> pkg_models.Pkg:
        source_and_id = {'pkg_source': row_mapping['source'], 'pkg_id': row_mapping['id']}
        return _make_db_pkg_converter().structure(
            {
                **row_mapping,
                'options': connection.execute(
                    sa.select(pkg_db.pkg_options).filter_by(**source_and_id)
                )
                .mappings()
                .one(),
                'folders': connection.execute(
                    sa.select(pkg_db.pkg_folder.c.name).filter_by(**source_and_id)
                )
                .mappings()
                .all(),
                'deps': connection.execute(
                    sa.select(pkg_db.pkg_dep.c.id).filter_by(**source_and_id)
                )
                .mappings()
                .all(),
                'logged_versions': connection.execute(
                    sa.select(pkg_db.pkg_version_log)
                    .filter_by(**source_and_id)
                    .order_by(pkg_db.pkg_version_log.c.install_time.desc())
                    .limit(10)
                )
                .mappings()
                .all(),
            },
            pkg_models.Pkg,
        )

    async def find_equivalent_pkg_defns(
        self, pkgs: Collection[pkg_models.Pkg]
    ) -> dict[pkg_models.Pkg, list[Defn]]:
        "Given a list of packages, find ``Defn``s of each package from other sources."
        from .matchers import AddonFolder

        catalogue = await self.ctx.synchronise()

        @run_in_thread
        def collect_addon_folders():
            return {
                p: frozenset(
                    a
                    for f in p.folders
                    for a in (
                        AddonFolder.from_addon_path(
                            self.ctx.config.game_flavour,
                            self.ctx.config.addon_dir / f.name,
                        ),
                    )
                    if a
                )
                for p in pkgs
            }

        async def collect_hashed_folder_defns():
            matches = [
                m
                for r in self.ctx.resolvers.values()
                for m in await r.get_folder_hash_matches(
                    [a for p, f in folders_per_pkg.items() if p.source != r.metadata.id for a in f]
                )
            ]

            defns_per_pkg: dict[pkg_models.Pkg, frozenset[Defn]] = {
                p: frozenset() for p in folders_per_pkg
            }
            for (pkg, orig_folders), (defn, matched_folders) in product(
                folders_per_pkg.items(), matches
            ):
                if orig_folders == matched_folders:
                    defns_per_pkg[pkg] |= frozenset((defn,))

            return defns_per_pkg

        def get_catalogue_defns(pkg: pkg_models.Pkg) -> frozenset[Defn]:
            entry = catalogue.keyed_entries.get((pkg.source, pkg.id))
            if entry:
                return frozenset(Defn(s.source, s.id) for s in entry.same_as)
            else:
                return frozenset()

        def get_addon_toc_defns(pkg_source: str, addon_folders: Collection[AddonFolder]):
            return frozenset(
                d
                for a in addon_folders
                for d in a.get_defns_from_toc_keys(self.ctx.resolvers.addon_toc_key_and_id_pairs)
                if d.source != pkg_source
            )

        folders_per_pkg = await collect_addon_folders()

        with time_op(lambda t: logger.debug(f'hashed folder matches found in {t:.3f}s')):
            hashed_folder_defns = await collect_hashed_folder_defns()

        return {
            p: sorted(d, key=lambda d: self.ctx.resolvers.priority_dict[d.source])
            for p in pkgs
            for d in (
                get_catalogue_defns(p)
                | get_addon_toc_defns(p.source, folders_per_pkg[p])
                | hashed_folder_defns[p],
            )
            if d
        }

    async def _resolve_deps(
        self, results: Collection[R.AnyResult[pkg_models.Pkg]]
    ) -> Mapping[Defn, R.AnyResult[pkg_models.Pkg]]:
        """Resolve package dependencies.

        The resolver will not follow dependencies
        more than one level deep.  This is to avoid unnecessary
        complexity for something that I would never expect to
        encounter in the wild.
        """
        pkgs = [r for r in results if isinstance(r, pkg_models.Pkg)]
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
            evolve(d, alias=r.slug) if isinstance(r, pkg_models.Pkg) else d: r
            for d, r in deps.items()
        }
        return pretty_deps

    async def resolve(
        self, defns: Collection[Defn], with_deps: bool = False
    ) -> Mapping[Defn, R.AnyResult[pkg_models.Pkg]]:
        "Resolve definitions into packages."
        if not defns:
            return {}

        defns_by_source = bucketise(defns, key=lambda v: v.source)
        results = await gather(
            (
                self.ctx.resolvers.get(s, _DummyResolver).resolve(b)
                for s, b in defns_by_source.items()
            ),
            R.resultify_async_exc,
        )
        results_by_defn = chain_dict(
            defns,
            R.ManagerError(),
            *(
                r.items() if isinstance(r, dict) else zip(d, repeat(r))
                for d, r in zip(defns_by_source.values(), results)
            ),
        )
        if with_deps:
            results_by_defn.update(await self._resolve_deps(results_by_defn.values()))
        return results_by_defn

    async def get_changelog(self, source: str, uri: str) -> str:
        "Retrieve a changelog from a URI."
        return await self.ctx.resolvers.get(source, _DummyResolver).get_changelog(URL(uri))

    @run_in_thread
    def _check_installed_pkg_integrity(self, pkg: pkg_models.Pkg) -> bool:
        return all((self.ctx.config.addon_dir / p.name).exists() for p in pkg.folders)

    async def _should_update_pkg(self, old_pkg: pkg_models.Pkg, new_pkg: pkg_models.Pkg) -> bool:
        return old_pkg.version != new_pkg.version or (
            not await self._check_installed_pkg_integrity(old_pkg)
        )

    @_with_lock(_MUTATE_PKGS_LOCK)
    async def install(
        self, defns: Sequence[Defn], replace_folders: bool, dry_run: bool = False
    ) -> Mapping[Defn, R.AnyResult[R.PkgInstalled]]:
        "Install packages from a definition list."

        # We'll weed out installed deps from the results after resolving -
        # doing it this way isn't particularly efficient but avoids having to
        # deal with local state in ``resolve``
        resolve_results = await self.resolve(
            [d for d in defns if not self.check_pkg_exists(d)], with_deps=True
        )
        pkgs, resolve_errors = bucketise_results(resolve_results.items())
        new_pkgs = {d: p for d, p in pkgs.items() if not self.check_pkg_exists(p.to_defn())}

        results = dict.fromkeys(defns, R.PkgAlreadyInstalled()) | resolve_errors

        if dry_run:
            return results | {d: R.PkgInstalled(p, dry_run=True) for d, p in new_pkgs.items()}

        download_results = zip(
            new_pkgs,
            await gather(
                (_download_pkg_archive(self.ctx, d, r) for d, r in new_pkgs.items()),
                R.resultify_async_exc,
            ),
        )
        archive_paths, download_errors = bucketise_results(download_results)

        return (
            results
            | download_errors
            | {
                d: await R.resultify_async_exc(
                    _install_pkg(self.ctx, new_pkgs[d], a, replace_folders)
                )
                for d, a in archive_paths.items()
            }
        )

    @_with_lock(_MUTATE_PKGS_LOCK)
    async def update(
        self, defns: Sequence[Defn], retain_defn_strategy: bool, dry_run: bool = False
    ) -> Mapping[Defn, R.AnyResult[R.PkgInstalled | R.PkgUpdated]]:
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
            evolve(d, id=p.id) if retain_defn_strategy else p.to_defn(): d
            for d, p in defns_to_pkgs.items()
        }
        resolve_results = await self.resolve(resolve_defns, with_deps=True)
        # Discard the reconstructed ``Defn``s
        orig_defn_resolve_results = (
            (resolve_defns.get(d, d), r) for d, r in resolve_results.items()
        )
        pkgs, resolve_errors = bucketise_results(orig_defn_resolve_results)

        updatables = {
            d: (o, n)
            for d, n in pkgs.items()
            for o in (defns_to_pkgs.get(d),)
            if not o or await self._should_update_pkg(o, n)
        }

        results = (
            dict.fromkeys(defns, R.PkgNotInstalled())
            | resolve_errors
            | {
                d: R.PkgUpToDate(is_pinned=pkgs[d].options.version_eq)
                for d in pkgs.keys() - updatables.keys()
            }
        )

        if dry_run:
            return results | {
                d: R.PkgUpdated(o, n, dry_run=True) if o else R.PkgInstalled(n, dry_run=True)
                for d, (o, n) in updatables.items()
            }

        download_results = zip(
            updatables,
            await gather(
                (_download_pkg_archive(self.ctx, d, n) for d, (_, n) in updatables.items()),
                R.resultify_async_exc,
            ),
        )
        archive_paths, download_errors = bucketise_results(download_results)

        return (
            results
            | download_errors
            | {
                d: await R.resultify_async_exc(
                    _update_pkg(self.ctx, o, n, a) if o else _install_pkg(self.ctx, n, a, False)
                )
                for d, a in archive_paths.items()
                for o, n in (updatables[d],)
            }
        )

    @_with_lock(_MUTATE_PKGS_LOCK)
    async def remove(
        self, defns: Sequence[Defn], keep_folders: bool
    ) -> Mapping[Defn, R.AnyResult[R.PkgRemoved]]:
        "Remove packages by their definition."
        return {
            d: (
                await R.resultify_async_exc(_remove_pkg(self.ctx, p, keep_folders))
                if p
                else R.PkgNotInstalled()
            )
            for d in defns
            for p in (self.get_pkg(d),)
        }

    @_with_lock(_MUTATE_PKGS_LOCK)
    async def pin(self, defns: Sequence[Defn]) -> Mapping[Defn, R.AnyResult[R.PkgInstalled]]:
        """Pin and unpin installed packages.

        instawow does not have true pinning.  This flips ``Strategy.VersionEq``
        on for installed packages from sources that support it.
        The net effect is the same as if the package
        had been reinstalled with the ``VersionEq`` strategy.
        """

        @run_in_thread
        def pin(defn: Defn) -> R.PkgInstalled:
            resolver = self.ctx.resolvers.get(defn.source)
            if resolver is None:
                raise R.PkgSourceInvalid

            if Strategy.VersionEq not in resolver.metadata.strategies:
                raise R.PkgStrategiesUnsupported({Strategy.VersionEq})

            pkg = self.get_pkg(defn)
            if not pkg:
                raise R.PkgNotInstalled

            version = defn.strategies.version_eq
            if version and pkg.version != version:
                R.PkgFilesNotMatching(defn.strategies)

            with self.ctx.database.begin() as transaction:
                transaction.execute(
                    sa.update(pkg_db.pkg_options)
                    .filter_by(pkg_source=pkg.source, pkg_id=pkg.id)
                    .values(version_eq=version is not None)
                )

            new_pkg = evolve(pkg, options=evolve(pkg.options, version_eq=version is not None))
            return R.PkgInstalled(new_pkg)

        return {d: await R.resultify_async_exc(pin(d)) for d in defns}
