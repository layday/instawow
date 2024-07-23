from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from functools import wraps
from itertools import chain, compress, filterfalse, repeat, starmap
from pathlib import Path
from typing import Concatenate, Literal, TypeVar

import attrs
from typing_extensions import Never, ParamSpec
from yarl import URL

from . import pkg_models, shared_ctx
from . import results as R
from ._progress_reporting import make_incrementing_progress_tracker
from ._utils.aio import gather, run_in_thread
from ._utils.file import trash
from ._utils.iteration import bucketise, uniq
from .definitions import Defn, Strategy
from .pkg_archives._download import download_pkg_archive
from .pkg_db import _ops as pkg_db_ops

_T = TypeVar('_T')
_P = ParamSpec('_P')

_MUTATE_PKGS_LOCK = '_MUTATE_PKGS_'


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


def _with_lock(lock_name: str):
    def outer(
        coro_fn: Callable[Concatenate[shared_ctx.ConfigBoundCtx, _P], Awaitable[_T]],
    ) -> Callable[Concatenate[shared_ctx.ConfigBoundCtx, _P], Awaitable[_T]]:
        @wraps(coro_fn)
        async def inner(
            config_ctx: shared_ctx.ConfigBoundCtx, *args: _P.args, **kwargs: _P.kwargs
        ) -> _T:
            async with shared_ctx.locks[lock_name, config_ctx.config.profile]:
                return await coro_fn(config_ctx, *args, **kwargs)

        return inner

    return outer


def get_alias_from_url(
    config_ctx: shared_ctx.ConfigBoundCtx, value: str
) -> tuple[str, str] | None:
    "Attempt to extract a valid ``Defn`` source and alias from a URL."
    url = URL(value)
    return next(
        (
            (r.metadata.id, a)
            for r in config_ctx.resolvers.values()
            if (a := r.get_alias_from_url(url))
        ),
        None,
    )


def _check_pkgs_not_exist(
    config_ctx: shared_ctx.ConfigBoundCtx, defns: Collection[Defn]
) -> list[bool]:
    "Check that packages exist in the database."
    if not defns:
        return []

    with (
        config_ctx.database.connect() as connection,
        config_ctx.database.use_tuple_factory(connection) as cursor,
    ):
        return [
            e
            for (e,) in cursor.execute(
                f"""
                WITH defn (source, alias, id)
                AS (
                    VALUES {", ".join(("(?, ?, ?)",) * len(defns))}
                )
                SELECT NOT EXISTS (
                    SELECT 1
                    FROM pkg
                    WHERE pkg.source = defn.source AND (
                        pkg.id = defn.alias OR pkg.id = defn.id OR lower(pkg.slug) = lower(defn.alias)
                    )
                )
                FROM defn
                """,
                tuple(i for d in defns for i in (d.source, d.alias, d.id)),
            ).fetchall()
        ]


def get_pkgs(
    config_ctx: shared_ctx.ConfigBoundCtx, defns: Collection[Defn] | Literal['all']
) -> list[pkg_models.Pkg | None]:
    if defns != 'all' and not defns:
        return []

    with config_ctx.database.connect() as connection:
        if defns == 'all':
            pkgs = connection.execute(
                """
                SELECT * FROM pkg
                """,
            ).fetchall()
        else:
            pkgs = connection.execute(
                f"""
                WITH defn (source, alias, id)
                AS (
                    VALUES {", ".join(("(?, ?, ?)",) * len(defns))}
                )
                SELECT pkg.*
                FROM defn
                LEFT JOIN pkg ON pkg.source = defn.source AND (
                    pkg.id = defn.alias OR pkg.id = defn.id OR lower(pkg.slug) = lower(defn.alias)
                )
                """,
                tuple(i for d in defns for i in (d.source, d.alias, d.id)),
            ).fetchall()

        return [
            pkg_models.build_pkg_from_row_mapping(connection, m) if m['source'] else None
            for m in pkgs
        ]


def get_pkg(config_ctx: shared_ctx.ConfigBoundCtx, defn: Defn) -> pkg_models.Pkg | None:
    "Retrieve a package from the database."
    (pkg,) = get_pkgs(config_ctx, [defn])
    return pkg


async def find_equivalent_pkg_defns(
    config_ctx: shared_ctx.ConfigBoundCtx, pkgs: Collection[pkg_models.Pkg]
) -> dict[pkg_models.Pkg, list[Defn]]:
    "Given a list of packages, find ``Defn``s of each package from other sources."
    from .catalogue import synchronise as synchronise_catalogue
    from .matchers import AddonFolder

    catalogue = await synchronise_catalogue()

    @run_in_thread
    def collect_addon_folders():
        return {
            p: frozenset(
                a
                for f in p.folders
                for a in (
                    AddonFolder.from_path(
                        config_ctx.config.game_flavour,
                        config_ctx.config.addon_dir / f.name,
                    ),
                )
                if a
            )
            for p in pkgs
        }

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
            for d in a.get_defns_from_toc_keys(config_ctx.resolvers.addon_toc_key_and_id_pairs)
            if d.source != pkg_source
        )

    folders_per_pkg = await collect_addon_folders()

    return {
        p: sorted(d, key=lambda d: config_ctx.resolvers.priority_dict[d.source])
        for p in pkgs
        for d in (get_catalogue_defns(p) | get_addon_toc_defns(p.source, folders_per_pkg[p]),)
        if d
    }


async def _resolve_deps(
    config_ctx: shared_ctx.ConfigBoundCtx, results: Collection[R.AnyResult[pkg_models.Pkg]]
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

    deps = await resolve(config_ctx, list(starmap(Defn, dep_defns)))
    pretty_deps = {
        attrs.evolve(d, alias=r.slug) if isinstance(r, pkg_models.Pkg) else d: r
        for d, r in deps.items()
    }
    return pretty_deps


async def resolve(
    config_ctx: shared_ctx.ConfigBoundCtx, defns: Collection[Defn], with_deps: bool = False
) -> Mapping[Defn, R.AnyResult[pkg_models.Pkg]]:
    "Resolve definitions into packages."
    if not defns:
        return {}

    defns_by_source = bucketise(defns, key=lambda v: v.source)

    track_progress = make_incrementing_progress_tracker(len(defns_by_source), 'Resolving add-ons')

    results = await gather(
        track_progress(R.resultify_async_exc(config_ctx.resolvers.get_or_dummy(s).resolve(b)))
        for s, b in defns_by_source.items()
    )
    results_by_defn = dict(
        chain(
            zip(defns, repeat(R.ManagerError())),
            *(
                r.items() if isinstance(r, dict) else zip(d, repeat(r))
                for d, r in zip(defns_by_source.values(), results)
            ),
        )
    )
    if with_deps:
        results_by_defn |= await _resolve_deps(config_ctx, results_by_defn.values())

    return results_by_defn


async def get_changelog(config_ctx: shared_ctx.ConfigBoundCtx, source: str, uri: str) -> str:
    "Retrieve a changelog from a URI."
    return await config_ctx.resolvers.get_or_dummy(source).get_changelog(URL(uri))


@run_in_thread
def _install_pkg(
    config_ctx: shared_ctx.ConfigBoundCtx,
    pkg: pkg_models.Pkg,
    archive: Path,
    *,
    replace_folders: bool,
):
    with (
        config_ctx.resolvers.archive_opener_dict[pkg.source](archive) as (
            top_level_folders,
            extract,
        ),
        config_ctx.database.connect() as connection,
    ):
        installed_conflicts = connection.execute(
            f"""
            SELECT DISTINCT pkg.*
            FROM pkg
            JOIN pkg_folder ON pkg_folder.pkg_source = pkg.source AND pkg_folder.pkg_id = pkg.id
            WHERE pkg_folder.name IN ({', '.join(('?',) * len(top_level_folders))})
            """,
            tuple(top_level_folders),
        ).fetchall()
        if installed_conflicts:
            raise R.PkgConflictsWithInstalled(installed_conflicts)

        if replace_folders:
            trash(
                (config_ctx.config.addon_dir / f for f in top_level_folders),
                dest=config_ctx.config.global_config.temp_dir,
                missing_ok=True,
            )
        else:
            unreconciled_conflicts = top_level_folders & {
                f.name for f in config_ctx.config.addon_dir.iterdir()
            }
            if unreconciled_conflicts:
                raise R.PkgConflictsWithUnreconciled(unreconciled_conflicts)

        extract(config_ctx.config.addon_dir)

        pkg = attrs.evolve(
            pkg, folders=[pkg_models.PkgFolder(name=f) for f in sorted(top_level_folders)]
        )
        with config_ctx.database.transact(connection) as transaction:
            pkg_db_ops.insert_pkg(pkg, transaction)

    return R.PkgInstalled(pkg)


@run_in_thread
def _update_pkg(
    config_ctx: shared_ctx.ConfigBoundCtx,
    old_pkg: pkg_models.Pkg,
    new_pkg: pkg_models.Pkg,
    archive: Path,
):
    with (
        config_ctx.resolvers.archive_opener_dict[new_pkg.source](archive) as (
            top_level_folders,
            extract,
        ),
        config_ctx.database.connect() as connection,
    ):
        installed_conflicts = connection.execute(
            f"""
            SELECT DISTINCT pkg.*
            FROM pkg
            JOIN pkg_folder ON pkg_folder.pkg_source = pkg.source AND pkg_folder.pkg_id = pkg.id
            WHERE (pkg_folder.pkg_source != ? AND pkg_folder.pkg_id != ?)
                AND (pkg_folder.name IN ({', '.join(('?',) * len(top_level_folders))}))
            """,
            (new_pkg.source, new_pkg.id, *top_level_folders),
        ).fetchall()
        if installed_conflicts:
            raise R.PkgConflictsWithInstalled(installed_conflicts)

        unreconciled_conflicts = top_level_folders - {f.name for f in old_pkg.folders} & {
            f.name for f in config_ctx.config.addon_dir.iterdir()
        }
        if unreconciled_conflicts:
            raise R.PkgConflictsWithUnreconciled(unreconciled_conflicts)

        trash(
            (config_ctx.config.addon_dir / f.name for f in old_pkg.folders),
            dest=config_ctx.config.global_config.temp_dir,
            missing_ok=True,
        )
        extract(config_ctx.config.addon_dir)

        new_pkg = attrs.evolve(
            new_pkg, folders=[pkg_models.PkgFolder(name=f) for f in sorted(top_level_folders)]
        )
        with config_ctx.database.transact(connection) as transaction:
            pkg_db_ops.delete_pkg(old_pkg, transaction)
            pkg_db_ops.insert_pkg(new_pkg, transaction)

    return R.PkgUpdated(old_pkg, new_pkg)


@run_in_thread
def _remove_pkg(config_ctx: shared_ctx.ConfigBoundCtx, pkg: pkg_models.Pkg, *, keep_folders: bool):
    if not keep_folders:
        trash(
            (config_ctx.config.addon_dir / f.name for f in pkg.folders),
            dest=config_ctx.config.global_config.temp_dir,
            missing_ok=True,
        )

    with (
        config_ctx.database.connect() as connection,
        config_ctx.database.transact(connection) as transaction,
    ):
        pkg_db_ops.delete_pkg(pkg, transaction)

    return R.PkgRemoved(pkg)


@run_in_thread
def _check_installed_pkg_integrity(config_ctx: shared_ctx.ConfigBoundCtx, pkg: pkg_models.Pkg):
    return all((config_ctx.config.addon_dir / p.name).exists() for p in pkg.folders)


@_with_lock(_MUTATE_PKGS_LOCK)
async def install(
    config_ctx: shared_ctx.ConfigBoundCtx,
    defns: Sequence[Defn],
    *,
    replace_folders: bool,
    dry_run: bool = False,
) -> Mapping[Defn, R.AnyResult[R.PkgInstalled]]:
    "Install packages from a definition list."

    # We'll weed out installed deps from the results after resolving -
    # doing it this way isn't particularly efficient but avoids having to
    # deal with local state in ``resolve``.
    resolve_results = await resolve(
        config_ctx, list(compress(defns, _check_pkgs_not_exist(config_ctx, defns))), with_deps=True
    )
    pkgs, resolve_errors = bucketise_results(resolve_results.items())
    new_pkgs = dict(
        compress(
            pkgs.items(), _check_pkgs_not_exist(config_ctx, [p.to_defn() for p in pkgs.values()])
        )
    )

    results = dict.fromkeys(defns, R.PkgAlreadyInstalled()) | resolve_errors

    if dry_run:
        return results | {d: R.PkgInstalled(p, dry_run=True) for d, p in new_pkgs.items()}

    download_results = await gather(
        R.resultify_async_exc(download_pkg_archive(config_ctx, d, r.download_url))
        for d, r in new_pkgs.items()
    )
    archive_paths, download_errors = bucketise_results(zip(new_pkgs, download_results))

    track_progress = make_incrementing_progress_tracker(len(archive_paths), 'Installing')

    return (
        results
        | download_errors
        | {
            d: await track_progress(
                R.resultify_async_exc(
                    _install_pkg(config_ctx, new_pkgs[d], a, replace_folders=replace_folders)
                )
            )
            for d, a in archive_paths.items()
        }
    )


@_with_lock(_MUTATE_PKGS_LOCK)
async def replace(
    config_ctx: shared_ctx.ConfigBoundCtx, defns: Mapping[Defn, Defn]
) -> Mapping[Defn, R.AnyResult[R.PkgInstalled | R.PkgRemoved]]:
    "Replace installed packages with re-reconciled packages."

    inverse_defns = {v: k for k, v in defns.items()}
    if len(inverse_defns) != len(defns):
        raise ValueError('``defns`` must be unique')

    old_pkgs = {d: p for d, p in zip(defns, get_pkgs(config_ctx, defns)) if p}

    resolve_results = await resolve(
        config_ctx,
        list(compress(defns.values(), _check_pkgs_not_exist(config_ctx, defns.values()))),
        with_deps=True,
    )
    pkgs, resolve_errors = bucketise_results(resolve_results.items())
    new_pkgs = dict(
        compress(
            pkgs.items(), _check_pkgs_not_exist(config_ctx, [p.to_defn() for p in pkgs.values()])
        )
    )

    results = dict(
        chain.from_iterable(
            zip(
                ((d, R.PkgNotInstalled()) for d in defns),
                ((d, None) for d in defns.values()),
                strict=True,
            )
        )
    )
    results = results | resolve_errors

    download_results = await gather(
        R.resultify_async_exc(download_pkg_archive(config_ctx, d, r.download_url))
        for d, r in new_pkgs.items()
    )
    archive_paths, download_errors = bucketise_results(zip(new_pkgs, download_results))

    replace_coros = {
        k: R.resultify_async_exc(c)
        for d, a in archive_paths.items()
        for o in (inverse_defns[d],)
        for k, c in (
            (o, _remove_pkg(config_ctx, old_pkgs[o], keep_folders=False)),
            (d, _install_pkg(config_ctx, new_pkgs[d], a, replace_folders=False)),
        )
    }

    track_progress = make_incrementing_progress_tracker(len(replace_coros), 'Replacing')

    results = (
        results | download_errors | {k: await track_progress(c) for k, c in replace_coros.items()}
    )
    return {k: v for k, v in results.items() if v is not None}


@_with_lock(_MUTATE_PKGS_LOCK)
async def update(
    config_ctx: shared_ctx.ConfigBoundCtx,
    defns: Sequence[Defn] | Literal['all'],
    *,
    dry_run: bool = False,
) -> Mapping[Defn, R.AnyResult[R.PkgInstalled | R.PkgUpdated]]:
    "Update installed packages from a definition list."

    if defns == 'all':
        defns_to_pkgs = {p.to_defn(): p for p in get_pkgs(config_ctx, defns) if p}
        defns = list(defns_to_pkgs)

        resolve_defns = {d: d for d in defns_to_pkgs}

    else:
        defns_to_pkgs = {d: p for d, p in zip(defns, get_pkgs(config_ctx, defns)) if p}

        resolve_defns = {
            # Attach the source ID to each ``Defn`` from the
            # corresponding installed package.  Using the ID has the benefit
            # of resolving installed-but-renamed packages - the slug is
            # transient but the ID isn't
            attrs.evolve(d, id=p.id) if d.strategies.initialised else p.to_defn(): d
            for d, p in defns_to_pkgs.items()
        }

    resolve_results = await resolve(config_ctx, resolve_defns, with_deps=True)
    pkgs, resolve_errors = bucketise_results(
        # Discard the reconstructed ``Defn``s
        (resolve_defns.get(d) or d, r)
        for d, r in resolve_results.items()
    )

    updatables = {
        d: (o, n)
        for d, n in pkgs.items()
        for o in (defns_to_pkgs.get(d),)
        if not o
        or o.version != n.version
        or not await _check_installed_pkg_integrity(config_ctx, o)
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

    download_results = await gather(
        R.resultify_async_exc(download_pkg_archive(config_ctx, d, n.download_url))
        for d, (_, n) in updatables.items()
    )
    archive_paths, download_errors = bucketise_results(zip(updatables, download_results))

    track_progress = make_incrementing_progress_tracker(len(archive_paths), 'Updating')

    return (
        results
        | download_errors
        | {
            d: await track_progress(
                R.resultify_async_exc(
                    _update_pkg(config_ctx, o, n, a)
                    if o
                    else _install_pkg(config_ctx, n, a, replace_folders=False)
                )
            )
            for d, a in archive_paths.items()
            for o, n in (updatables[d],)
        }
    )


@_with_lock(_MUTATE_PKGS_LOCK)
async def remove(
    config_ctx: shared_ctx.ConfigBoundCtx, defns: Sequence[Defn], *, keep_folders: bool
) -> Mapping[Defn, R.AnyResult[R.PkgRemoved]]:
    "Remove packages by their definition."
    return {
        d: (
            await R.resultify_async_exc(_remove_pkg(config_ctx, p, keep_folders=keep_folders))
            if p
            else R.PkgNotInstalled()
        )
        for d, p in zip(defns, get_pkgs(config_ctx, defns))
    }


@_with_lock(_MUTATE_PKGS_LOCK)
async def pin(
    config_ctx: shared_ctx.ConfigBoundCtx, defns: Sequence[Defn]
) -> Mapping[Defn, R.AnyResult[R.PkgInstalled]]:
    """Pin and unpin installed packages.

    instawow does not have true pinning.  This flips ``Strategy.VersionEq``
    on for installed packages from sources that support it.
    The net effect is the same as if the package
    had been reinstalled with the ``VersionEq`` strategy.
    """

    async def pin(defn: Defn, pkg: pkg_models.Pkg | None) -> R.PkgInstalled:
        resolver = config_ctx.resolvers.get(defn.source)
        if resolver is None:
            raise R.PkgSourceInvalid
        elif Strategy.VersionEq not in resolver.metadata.strategies:
            raise R.PkgStrategiesUnsupported({Strategy.VersionEq})

        if not pkg:
            raise R.PkgNotInstalled

        version = defn.strategies[Strategy.VersionEq]
        if version and pkg.version != version:
            R.PkgFilesNotMatching(defn.strategies)

        version_eq = version is not None

        with (
            config_ctx.database.connect() as connection,
            config_ctx.database.transact(connection) as transaction,
        ):
            transaction.execute(
                """
                UPDATE pkg_options
                SET version_eq = :version_eq
                WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
                """,
                {
                    'pkg_source': pkg.source,
                    'pkg_id': pkg.id,
                    'version_eq': version_eq,
                },
            )

        return R.PkgInstalled(
            attrs.evolve(pkg, options=attrs.evolve(pkg.options, version_eq=version_eq)),
        )

    return {
        d: await R.resultify_async_exc(pin(d, p))
        for d, p in zip(defns, get_pkgs(config_ctx, defns))
    }
