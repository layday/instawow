from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from functools import partial, wraps
from itertools import chain, compress, filterfalse, repeat, starmap
from pathlib import Path
from typing import Literal, Never, TypedDict

from yarl import URL

from . import config_ctx, sync_ctx
from ._utils.aio import gather, run_in_thread
from ._utils.attrs import evolve
from ._utils.file import trash
from ._utils.iteration import bucketise, uniq
from .definitions import Defn, Strategy
from .pkg_archives._download import download_pkg_archive
from .pkg_db import Connection, Row, transact, use_tuple_factory
from .pkg_db.models import Pkg, PkgLoggedVersion, make_db_converter
from .progress_reporting import make_incrementing_progress_tracker
from .resolvers import PkgCandidate
from .results import (
    AnyResult,
    ManagerError,
    PkgAlreadyInstalled,
    PkgConflictsWithInstalled,
    PkgConflictsWithUnreconciled,
    PkgFilesNotMatching,
    PkgInstalled,
    PkgNotInstalled,
    PkgRemoved,
    PkgStrategiesUnsupported,
    PkgUpdated,
    PkgUpToDate,
    is_error_result,
    resultify,
)

_MUTATE_PKGS_LOCK = '_MUTATE_PKGS_'


_download_pkg_archive = resultify(download_pkg_archive)


def _with_mutate_lock[**P, T](
    coro_fn: Callable[P, Awaitable[T]],
) -> Callable[P, Awaitable[T]]:
    @wraps(coro_fn)
    async def inner(*args: P.args, **kwargs: P.kwargs) -> T:
        async with sync_ctx.locks()[_MUTATE_PKGS_LOCK, config_ctx.config().profile]:
            return await coro_fn(*args, **kwargs)

    return inner


def split_results[T](
    values: Iterable[tuple[Defn, AnyResult[T]]],
) -> tuple[dict[Defn, T], dict[Defn, AnyResult[Never]]]:
    ts: dict[Defn, T] = {}
    errors: dict[Defn, AnyResult[Never]] = {}

    for defn, value in values:
        if is_error_result(value):
            errors[defn] = value
        else:
            ts[defn] = value

    return ts, errors


def get_alias_from_url(value: str) -> tuple[str, str] | None:
    "Attempt to extract a valid ``Defn`` source and alias from a URL."
    resolvers = config_ctx.resolvers()
    url = URL(value)
    return next(
        ((r.metadata.id, a) for r in resolvers.values() if (a := r.get_alias_from_url(url))),
        None,
    )


async def get_changelog(source: str, uri: str) -> str:
    "Retrieve a changelog from a URI."
    return await config_ctx.resolvers().get_or_dummy(source).get_changelog(URL(uri))


def build_pkg_from_pkg_candidate(
    defn: Defn,
    pkg_candidate: PkgCandidate,
    *,
    folders: list[TypedDict[{'name': str}]],
) -> Pkg:
    return make_db_converter().structure(
        {
            'deps': [],
        }
        | pkg_candidate
        | {
            'source': defn.source,
            'options': {k: bool(v) for k, v in defn.strategies.items()},
            'folders': folders,
        },
        Pkg,
    )


def build_pkg_from_row_mapping(connection: Connection, row_mapping: Row) -> Pkg:
    fk = {'pkg_source': row_mapping['source'], 'pkg_id': row_mapping['id']}
    return make_db_converter().structure(
        {
            **row_mapping,
            'options': connection.execute(
                """
                SELECT any_flavour, any_release_type, version_eq
                FROM pkg_options
                WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
                """,
                fk,
            ).fetchone(),
            'folders': connection.execute(
                """
                SELECT name
                FROM pkg_folder
                WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
                """,
                fk,
            ).fetchall(),
            'deps': connection.execute(
                """
                SELECT id
                FROM pkg_dep
                WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
                """,
                fk,
            ).fetchall(),
        },
        Pkg,
    )


def _check_pkgs_not_exist(defns: Collection[Defn]) -> list[bool]:
    "Check that packages exist in the database."
    if not defns:
        return []

    with config_ctx.database() as connection, use_tuple_factory(connection) as cursor:
        return [
            e
            for (e,) in cursor.execute(
                f"""
                WITH defn (source, alias, id)
                AS (
                    VALUES {', '.join(('(?, ?, ?)',) * len(defns))}
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


def get_pkgs(defns: Collection[Defn] | Literal['all']) -> list[Pkg | None]:
    if defns != 'all' and not defns:
        return []

    with config_ctx.database() as connection:
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
                    VALUES {', '.join(('(?, ?, ?)',) * len(defns))}
                )
                SELECT pkg.*
                FROM defn
                LEFT JOIN pkg ON pkg.source = defn.source AND (
                    pkg.id = defn.alias OR pkg.id = defn.id OR lower(pkg.slug) = lower(defn.alias)
                )
                """,
                tuple(i for d in defns for i in (d.source, d.alias, d.id)),
            ).fetchall()

        return [build_pkg_from_row_mapping(connection, m) if m['source'] else None for m in pkgs]


def get_pinnable_pkgs(
    defns: Collection[Defn],
) -> list[AnyResult[Pkg]]:
    resolvers = config_ctx.resolvers()

    @resultify
    def validate_pkg(defn: Defn, pkg: Pkg | None):
        if Strategy.VersionEq not in resolvers.get_or_dummy(defn.source).metadata.strategies:
            raise PkgStrategiesUnsupported({Strategy.VersionEq})

        if not pkg:
            raise PkgNotInstalled()

        else:
            version = defn.strategies[Strategy.VersionEq]
            if version and pkg.version != version:
                raise PkgFilesNotMatching(defn.strategies)

        return pkg

    return list(map(validate_pkg, defns, get_pkgs(defns)))


def get_pkg_logged_versions(pkg: Pkg) -> list[PkgLoggedVersion]:
    convert = partial(make_db_converter().structure, cl=PkgLoggedVersion)

    with config_ctx.database() as connection:
        return [
            convert(v)
            for v in connection.execute(
                """
                SELECT version, install_time
                FROM pkg_version_log
                WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
                ORDER BY install_time DESC
                LIMIT 10
                """,
                {'pkg_source': pkg.source, 'pkg_id': pkg.id},
            ).fetchall()
        ]


def _insert_pkg(pkg: Pkg, transaction: Connection) -> None:
    pkg_values = make_db_converter().unstructure(pkg)

    transaction.execute(
        """
        INSERT INTO pkg (
            source,
            id,
            slug,
            name,
            description,
            url,
            download_url,
            date_published,
            version,
            changelog_url
        )
        VALUES (
            :source,
            :id,
            :slug,
            :name,
            :description,
            :url,
            :download_url,
            :date_published,
            :version,
            :changelog_url
        )
        """,
        pkg_values,
    )
    transaction.execute(
        """
        INSERT INTO pkg_options (
            any_flavour,
            any_release_type,
            version_eq,
            pkg_source,
            pkg_id
        )
        VALUES (
            :any_flavour,
            :any_release_type,
            :version_eq,
            :pkg_source,
            :pkg_id
        )
        """,
        pkg_values['options'] | {'pkg_source': pkg_values['source'], 'pkg_id': pkg_values['id']},
    )
    transaction.executemany(
        """
        INSERT INTO pkg_folder (
            name,
            pkg_source,
            pkg_id
        )
        VALUES (
            :name,
            :pkg_source,
            :pkg_id
        )
        """,
        [
            f | {'pkg_source': pkg_values['source'], 'pkg_id': pkg_values['id']}
            for f in pkg_values['folders']
        ],
    )
    if pkg_values['deps']:
        transaction.executemany(
            """
            INSERT INTO pkg_dep (
                id,
                pkg_source,
                pkg_id
            )
            VALUES (
                :id,
                :pkg_source,
                :pkg_id
            )
            """,
            [
                f | {'pkg_source': pkg_values['source'], 'pkg_id': pkg_values['id']}
                for f in pkg_values['deps']
            ],
        )
    transaction.execute(
        """
        INSERT OR IGNORE INTO pkg_version_log (
            version,
            pkg_source,
            pkg_id
        )
        VALUES (
            :version,
            :pkg_source,
            :pkg_id
        )
        """,
        {
            'version': pkg_values['version'],
            'pkg_source': pkg_values['source'],
            'pkg_id': pkg_values['id'],
        },
    )


def _delete_pkg(pkg: Pkg, transaction: Connection) -> None:
    transaction.execute(
        'DELETE FROM pkg WHERE source = :source AND id = :id',
        {
            'source': pkg.source,
            'id': pkg.id,
        },
    )


async def find_equivalent_pkg_defns(
    pkgs: Collection[Pkg],
) -> dict[Pkg, list[Defn]]:
    "Given a list of packages, find ``Defn``s of each package from other sources."
    from .catalogue import synchronise as synchronise_catalogue
    from .matchers import AddonFolder
    from .wow_installations import to_flavour

    config = config_ctx.config()
    resolvers = config_ctx.resolvers()
    flavour = to_flavour(config.track)

    catalogue = await synchronise_catalogue()

    @run_in_thread
    def collect_addon_folders():
        return {
            p: frozenset(
                a
                for f in p.folders
                for a in (AddonFolder.from_path(flavour, config.addon_dir / f.name),)
                if a
            )
            for p in pkgs
        }

    def get_catalogue_defns(pkg: Pkg) -> frozenset[Defn]:
        entry = catalogue.keyed_entries.get((pkg.source, pkg.id))
        return frozenset(Defn(s.source, s.id) for s in entry.same_as) if entry else frozenset()

    def get_addon_toc_defns(pkg_source: str, addon_folders: Collection[AddonFolder]):
        return frozenset(
            d
            for a in addon_folders
            for d in a.get_defns_from_toc_keys(resolvers.addon_toc_key_and_id_pairs)
            if d.source != pkg_source
        )

    folders_per_pkg = await collect_addon_folders()

    return {
        p: sorted(d, key=lambda d: resolvers.priority_dict[d.source])
        for p in pkgs
        for d in (get_catalogue_defns(p) | get_addon_toc_defns(p.source, folders_per_pkg[p]),)
        if d
    }


async def _resolve_deps(
    results: Mapping[Defn, AnyResult[PkgCandidate]],
) -> Mapping[Defn, AnyResult[PkgCandidate]]:
    """Resolve package dependencies.

    The resolver will not follow dependencies
    more than one level deep.  This is to avoid unnecessary
    complexity for something that I would never expect to
    encounter in the wild.
    """
    pkg_candidates, _ = split_results(results.items())
    dep_defns = uniq(
        filterfalse(
            {(d.source, p['id']) for d, p in pkg_candidates.items()}.__contains__,
            (
                (d.source, e['id'])
                for d, p in pkg_candidates.items()
                if 'deps' in p
                for e in p['deps']
            ),
        )
    )
    if not dep_defns:
        return {}

    # Map the ID both to the `alias` and the `id` fields of the `Defn` so that
    # it's not lost if we humanise the alias later.
    deps = await resolve(list(starmap(Defn, *zip((s, i, i) for s, i in dep_defns))))
    pretty_deps = {
        evolve(d, {'alias': r['slug']}) if isinstance(r, dict) else d: r for d, r in deps.items()
    }
    return pretty_deps


async def resolve(
    defns: Collection[Defn], with_deps: bool = False
) -> Mapping[Defn, AnyResult[PkgCandidate]]:
    "Resolve definitions into packages."
    if not defns:
        return {}

    resolvers = config_ctx.resolvers()

    defns_by_source = bucketise(defns, key=lambda v: v.source)

    track_progress = make_incrementing_progress_tracker(len(defns_by_source), 'Resolving add-ons')

    results = await gather(
        track_progress(resultify(resolvers.get_or_dummy(s).resolve)(b))
        for s, b in defns_by_source.items()
    )
    results_by_defn = dict(
        chain(
            zip(defns, repeat(ManagerError())),
            *(
                r.items() if isinstance(r, dict) else zip(d, repeat(r))
                for d, r in zip(defns_by_source.values(), results)
            ),
        )
    )
    if with_deps:
        results_by_defn |= await _resolve_deps(results_by_defn)

    return results_by_defn


@resultify
@run_in_thread
def _mutate_install(
    defn: Defn, pkg_candidate: PkgCandidate, archive: Path, *, replace_folders: bool
):
    with (
        config_ctx.resolvers().archive_opener_dict[defn.source](
            archive,
        ) as (top_level_folders, extract),
        config_ctx.database() as connection,
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
            raise PkgConflictsWithInstalled(installed_conflicts)

        config = config_ctx.config()

        if replace_folders:
            trash(config.addon_dir / f for f in top_level_folders)
        else:
            unreconciled_conflicts = top_level_folders & {
                f.name for f in config.addon_dir.iterdir()
            }
            if unreconciled_conflicts:
                raise PkgConflictsWithUnreconciled(unreconciled_conflicts)

        extract(config.addon_dir)

        pkg = build_pkg_from_pkg_candidate(
            defn, pkg_candidate, folders=[{'name': f} for f in sorted(top_level_folders)]
        )
        with transact(connection) as transaction:
            _insert_pkg(pkg, transaction)

    return PkgInstalled(pkg)


@resultify
@run_in_thread
def _mutate_update(defn: Defn, old_pkg: Pkg, pkg_candidate: PkgCandidate, archive: Path):
    with (
        config_ctx.resolvers().archive_opener_dict[defn.source](
            archive,
        ) as (top_level_folders, extract),
        config_ctx.database() as connection,
    ):
        installed_conflicts = connection.execute(
            f"""
            SELECT DISTINCT pkg.*
            FROM pkg
            JOIN pkg_folder ON pkg_folder.pkg_source = pkg.source AND pkg_folder.pkg_id = pkg.id
            WHERE (pkg_folder.pkg_source != ? AND pkg_folder.pkg_id != ?)
                AND (pkg_folder.name IN ({', '.join(('?',) * len(top_level_folders))}))
            """,
            (defn.source, pkg_candidate['id'], *top_level_folders),
        ).fetchall()
        if installed_conflicts:
            raise PkgConflictsWithInstalled(installed_conflicts)

        config = config_ctx.config()

        unreconciled_conflicts = top_level_folders - {f.name for f in old_pkg.folders} & {
            f.name for f in config.addon_dir.iterdir()
        }
        if unreconciled_conflicts:
            raise PkgConflictsWithUnreconciled(unreconciled_conflicts)

        trash(config.addon_dir / f.name for f in old_pkg.folders)
        extract(config.addon_dir)

        new_pkg = build_pkg_from_pkg_candidate(
            defn, pkg_candidate, folders=[{'name': f} for f in sorted(top_level_folders)]
        )
        with transact(connection) as transaction:
            _delete_pkg(old_pkg, transaction)
            _insert_pkg(new_pkg, transaction)

    return PkgUpdated(old_pkg, new_pkg)


@resultify
@run_in_thread
def _mutate_remove(defn: Defn, pkg: Pkg, *, keep_folders: bool):
    if not keep_folders:
        config = config_ctx.config()
        trash(config.addon_dir / f.name for f in pkg.folders)

    with config_ctx.database() as connection, transact(connection) as transaction:
        _delete_pkg(pkg, transaction)

    return PkgRemoved(pkg)


@resultify
def _mutate_pin(defn: Defn, pkg: Pkg):
    with config_ctx.database() as connection, transact(connection) as transaction:
        (version_eq,) = transaction.execute(
            """
            UPDATE pkg_options
            SET version_eq = :version_eq
            WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
            RETURNING version_eq
            """,
            {
                'pkg_source': pkg.source,
                'pkg_id': pkg.id,
                'version_eq': defn.strategies[Strategy.VersionEq] is not None,
            },
        ).fetchone()

    return PkgInstalled(
        evolve(pkg, {'options': {'version_eq': bool(version_eq)}}),
    )


@run_in_thread
def _check_installed_pkg_integrity(addon_dir: Path, pkg: Pkg):
    return all((addon_dir / p.name).exists() for p in pkg.folders)


@_with_mutate_lock
async def install(
    defns: Sequence[Defn],
    *,
    replace_folders: bool,
    dry_run: bool = False,
) -> Mapping[Defn, AnyResult[PkgInstalled]]:
    "Install packages from a definition list."

    # We'll weed out installed deps from the results after resolving -
    # doing it this way isn't particularly efficient but avoids having to
    # deal with local state in ``resolve``.
    resolve_results = await resolve(
        list(compress(defns, _check_pkgs_not_exist(defns))), with_deps=True
    )
    pkg_candidates, resolve_errors = split_results(resolve_results.items())
    pkg_candidates = dict(
        compress(
            pkg_candidates.items(),
            _check_pkgs_not_exist([evolve(d, {'id': c['id']}) for d, c in pkg_candidates.items()]),
        )
    )

    results = dict.fromkeys(defns, PkgAlreadyInstalled()) | resolve_errors

    if dry_run:
        return results | {
            d: PkgInstalled(build_pkg_from_pkg_candidate(d, p, folders=[]), dry_run=True)
            for d, p in pkg_candidates.items()
        }

    download_results = await gather(
        _download_pkg_archive(d, r['download_url']) for d, r in pkg_candidates.items()
    )
    archive_paths, download_errors = split_results(zip(pkg_candidates, download_results))

    track_progress = make_incrementing_progress_tracker(len(archive_paths), 'Installing')

    return (
        results
        | download_errors
        | {
            d: await track_progress(
                _mutate_install(d, pkg_candidates[d], a, replace_folders=replace_folders)
            )
            for d, a in archive_paths.items()
        }
    )


@_with_mutate_lock
async def replace(
    defns: Mapping[Defn, Defn],
) -> Mapping[Defn, AnyResult[PkgInstalled | PkgRemoved]]:
    "Replace installed packages with re-reconciled packages."

    inverse_defns = {v: k for k, v in defns.items()}
    if len(inverse_defns) != len(defns):
        raise ValueError('``defns`` must be unique')

    old_pkgs = {d: p for d, p in zip(defns, get_pkgs(defns)) if p}

    resolve_results = await resolve(
        list(compress(defns.values(), _check_pkgs_not_exist(defns.values()))),
        with_deps=True,
    )
    pkg_candidates, resolve_errors = split_results(resolve_results.items())
    pkg_candidates = dict(
        compress(
            pkg_candidates.items(),
            _check_pkgs_not_exist([evolve(d, {'id': c['id']}) for d, c in pkg_candidates.items()]),
        )
    )

    results = dict(
        chain.from_iterable(
            zip(
                ((d, PkgNotInstalled()) for d in defns),
                ((d, None) for d in defns.values()),
                strict=True,
            )
        )
    )
    results = results | resolve_errors

    download_results = await gather(
        _download_pkg_archive(d, r['download_url']) for d, r in pkg_candidates.items()
    )
    archive_paths, download_errors = split_results(zip(pkg_candidates, download_results))

    replace_coros = {
        k: c
        for d, a in archive_paths.items()
        for o in (inverse_defns[d],)
        for k, c in (
            (o, _mutate_remove(d, old_pkgs[o], keep_folders=False)),
            (d, _mutate_install(d, pkg_candidates[d], a, replace_folders=False)),
        )
    }

    track_progress = make_incrementing_progress_tracker(len(replace_coros), 'Replacing')

    results = (
        results | download_errors | {k: await track_progress(c) for k, c in replace_coros.items()}
    )
    return {k: v for k, v in results.items() if v is not None}


@_with_mutate_lock
async def update(
    defns: Sequence[Defn] | Literal['all'],
    *,
    dry_run: bool = False,
) -> Mapping[Defn, AnyResult[PkgInstalled | PkgUpdated]]:
    "Update installed packages from a definition list."

    config = config_ctx.config()

    if defns == 'all':
        defns_to_pkgs = {p.to_defn(): p for p in get_pkgs(defns) if p}
        defns = list(defns_to_pkgs)
        resolve_defns = {d: d for d in defns_to_pkgs}

    else:
        defns_to_pkgs = {d: p for d, p in zip(defns, get_pkgs(defns)) if p}
        resolve_defns = {
            # Attach the source ID to each ``Defn`` from the
            # corresponding installed package.  Using the ID has the benefit
            # of resolving installed-but-renamed packages - the slug is
            # transient but the ID isn't
            evolve(d, {'id': p.id}) if d.strategies else p.to_defn(): d
            for d, p in defns_to_pkgs.items()
        }

    resolve_results = await resolve(resolve_defns, with_deps=True)
    pkg_candidates, resolve_errors = split_results(
        # Discard the reconstructed ``Defn``s
        (resolve_defns.get(d) or d, r)
        for d, r in resolve_results.items()
    )

    updatables = {
        d: (o, n)
        for d, n in pkg_candidates.items()
        for o in (defns_to_pkgs.get(d),)
        if not o
        or o.version != n['version']
        or not await _check_installed_pkg_integrity(config.addon_dir, o)
    }

    results = (
        dict.fromkeys(defns, PkgNotInstalled())
        | resolve_errors
        | {
            d: PkgUpToDate(is_pinned=bool(defns_to_pkgs[d].options.version_eq))
            for d in pkg_candidates.keys() - updatables.keys()
        }
    )

    if dry_run:
        return results | {
            d: PkgUpdated(o, build_pkg_from_pkg_candidate(d, n, folders=[]), dry_run=True)
            if o
            else PkgInstalled(build_pkg_from_pkg_candidate(d, n, folders=[]), dry_run=True)
            for d, (o, n) in updatables.items()
        }

    download_results = await gather(
        _download_pkg_archive(d, n['download_url']) for d, (_, n) in updatables.items()
    )
    archive_paths, download_errors = split_results(zip(updatables, download_results))

    track_progress = make_incrementing_progress_tracker(len(archive_paths), 'Updating')

    return (
        results
        | download_errors
        | {
            d: await track_progress(
                _mutate_update(d, o, n, a)
                if o
                else _mutate_install(d, n, a, replace_folders=False)
            )
            for d, a in archive_paths.items()
            for o, n in (updatables[d],)
        }
    )


@_with_mutate_lock
async def remove(
    defns: Sequence[Defn], *, keep_folders: bool
) -> Mapping[Defn, AnyResult[PkgRemoved]]:
    "Remove packages by their definition."
    return {
        d: await _mutate_remove(d, p, keep_folders=keep_folders) if p else PkgNotInstalled()
        for d, p in zip(defns, get_pkgs(defns))
    }


@_with_mutate_lock
async def pin(defns: Sequence[Defn]) -> Mapping[Defn, AnyResult[PkgInstalled]]:
    """Pin and unpin installed packages.

    instawow does not have true pinning.  This flips ``Strategy.VersionEq``
    on for installed packages from sources that support it.
    The net effect is the same as if the package
    had been reinstalled with the ``VersionEq`` strategy.
    """
    return {
        d: r if is_error_result(r) else _mutate_pin(d, r)
        for d, r in zip(defns, get_pinnable_pkgs(defns))
    }
