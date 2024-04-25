from __future__ import annotations

from collections.abc import (
    Awaitable,
    Callable,
    Collection,
    Iterable,
    Mapping,
    Sequence,
)
from contextlib import asynccontextmanager, nullcontext
from functools import wraps
from itertools import compress, filterfalse, product, repeat, starmap
from pathlib import Path
from shutil import move
from tempfile import NamedTemporaryFile
from typing import Concatenate, Literal, TypeVar

import attrs
from typing_extensions import Never, ParamSpec
from yarl import URL

from . import pkg_db, pkg_models
from . import results as R
from ._logging import logger
from ._utils.aio import gather, run_in_thread
from ._utils.file import trash
from ._utils.iteration import bucketise, chain_dict, uniq
from ._utils.perf import time_op
from ._utils.text import shasum
from ._utils.web import file_uri_to_path, is_file_uri
from .definitions import Defn, Strategy
from .http import CACHE_INDEFINITELY, ProgressCtx
from .manager_ctx import ManagerCtx
from .resolvers import HeadersIntent

_T = TypeVar('_T')
_TPkgManager = TypeVar('_TPkgManager', bound='PkgManager')
_P = ParamSpec('_P')

_AsyncNamedTemporaryFile = run_in_thread(NamedTemporaryFile)
_move_async = run_in_thread(move)

_MUTATE_PKGS_LOCK = '_MUTATE_PKGS_'
_DOWNLOAD_PKG_LOCK = '_DOWNLOAD_PKG_'


class PkgDownloadTraceRequestCtx(ProgressCtx[Literal['pkg_download']]):
    profile: str
    defn: Defn


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


async def _download_pkg_archive(ctx: ManagerCtx, defn: Defn, pkg: pkg_models.Pkg) -> Path:
    if is_file_uri(pkg.download_url):
        return Path(file_uri_to_path(pkg.download_url))

    async with ctx.locks[_DOWNLOAD_PKG_LOCK, pkg.download_url]:
        headers = await ctx.resolvers[pkg.source].make_request_headers(
            intent=HeadersIntent.Download
        )
        trace_request_ctx = PkgDownloadTraceRequestCtx(
            report_progress='pkg_download', profile=ctx.config.profile, defn=defn
        )

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


def _insert_db_pkg(pkg: pkg_models.Pkg, transaction: pkg_db.Connection):
    pkg_values = pkg_models.make_db_converter().unstructure(pkg)

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


def _delete_db_pkg(pkg: pkg_models.Pkg, transaction: pkg_db.Connection):
    transaction.execute(
        'DELETE FROM pkg WHERE source = :source AND id = :id',
        pkg_models.make_db_converter().unstructure(pkg),
    )


@run_in_thread
def _install_pkg(
    ctx: ManagerCtx, pkg: pkg_models.Pkg, archive: Path, *, replace_folders: bool
) -> R.PkgInstalled:
    with (
        ctx.resolvers.archive_opener_dict[pkg.source](archive) as (top_level_folders, extract),
        ctx.database.connect() as connection,
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

        pkg = attrs.evolve(
            pkg, folders=[pkg_models.PkgFolder(name=f) for f in sorted(top_level_folders)]
        )
        with ctx.database.transact(connection) as transaction:
            _insert_db_pkg(pkg, transaction)

    return R.PkgInstalled(pkg)


@run_in_thread
def _update_pkg(
    ctx: ManagerCtx, old_pkg: pkg_models.Pkg, new_pkg: pkg_models.Pkg, archive: Path
) -> R.PkgUpdated:
    with (
        ctx.resolvers.archive_opener_dict[new_pkg.source](archive) as (top_level_folders, extract),
        ctx.database.connect() as connection,
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

        new_pkg = attrs.evolve(
            new_pkg, folders=[pkg_models.PkgFolder(name=f) for f in sorted(top_level_folders)]
        )
        with ctx.database.transact(connection) as transaction:
            _delete_db_pkg(old_pkg, transaction)
            _insert_db_pkg(new_pkg, transaction)

    return R.PkgUpdated(old_pkg, new_pkg)


@run_in_thread
def _remove_pkg(ctx: ManagerCtx, pkg: pkg_models.Pkg, *, keep_folders: bool) -> R.PkgRemoved:
    if not keep_folders:
        trash(
            (ctx.config.addon_dir / f.name for f in pkg.folders),
            dest=ctx.config.global_config.temp_dir,
            missing_ok=True,
        )

    with ctx.database.connect() as connection, ctx.database.transact(connection) as transaction:
        _delete_db_pkg(pkg, transaction)

    return R.PkgRemoved(pkg)


@run_in_thread
def _check_installed_pkg_integrity(ctx: ManagerCtx, pkg: pkg_models.Pkg):
    return all((ctx.config.addon_dir / p.name).exists() for p in pkg.folders)


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
        url = URL(value)
        return next(
            (
                (r.metadata.id, a)
                for r in self.ctx.resolvers.values()
                if (a := r.get_alias_from_url(url))
            ),
            None,
        )

    def check_pkgs_exist(
        self,
        defns: Sequence[Defn],
        *,
        connection: pkg_db.Connection | None = None,
    ) -> list[bool]:
        "Check that packages exist in the database."
        if not defns:
            return []

        with (
            nullcontext(connection) if connection else self.ctx.database.connect() as connection,
            self.ctx.database.use_tuple_factory(connection) as cursor,
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
        self,
        defns: Sequence[Defn] | Literal['all'],
        *,
        connection: pkg_db.Connection | None = None,
    ) -> list[pkg_models.Pkg | None]:
        if defns != 'all' and not defns:
            return []

        with nullcontext(connection) if connection else self.ctx.database.connect() as connection:
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
                self.build_pkg_from_row_mapping(connection, m) if m['source'] else None
                for m in pkgs
            ]

    def get_pkg(
        self,
        defn: Defn,
        *,
        connection: pkg_db.Connection | None = None,
    ) -> pkg_models.Pkg | None:
        "Retrieve a package from the database."
        (pkg,) = self.get_pkgs([defn], connection=connection)
        return pkg

    def build_pkg_from_row_mapping(
        self, connection: pkg_db.Connection, row_mapping: pkg_db.Row
    ) -> pkg_models.Pkg:
        fk = {'pkg_source': row_mapping['source'], 'pkg_id': row_mapping['id']}
        return pkg_models.make_db_converter().structure(
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
                'logged_versions': connection.execute(
                    """
                    SELECT version, install_time
                    FROM pkg_version_log
                    WHERE pkg_source = :pkg_source AND pkg_id = :pkg_id
                    ORDER BY install_time DESC
                    LIMIT 10
                    """,
                    fk,
                ).fetchall(),
            },
            pkg_models.Pkg,
        )

    async def find_equivalent_pkg_defns(
        self, pkgs: Collection[pkg_models.Pkg]
    ) -> dict[pkg_models.Pkg, list[Defn]]:
        "Given a list of packages, find ``Defn``s of each package from other sources."
        from .catalogue import synchronise as synchronise_catalogue
        from .matchers import AddonFolder

        catalogue = await synchronise_catalogue(self.ctx)

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
            attrs.evolve(d, alias=r.slug) if isinstance(r, pkg_models.Pkg) else d: r
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
            R.resultify_async_exc(self.ctx.resolvers.get(s, _DummyResolver).resolve(b))
            for s, b in defns_by_source.items()
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

    @_with_lock(_MUTATE_PKGS_LOCK)
    async def install(
        self, defns: Sequence[Defn], *, replace_folders: bool, dry_run: bool = False
    ) -> Mapping[Defn, R.AnyResult[R.PkgInstalled]]:
        "Install packages from a definition list."

        # We'll weed out installed deps from the results after resolving -
        # doing it this way isn't particularly efficient but avoids having to
        # deal with local state in ``resolve``.
        resolve_results = await self.resolve(
            list(compress(defns, self.check_pkgs_exist(defns))), with_deps=True
        )
        pkgs, resolve_errors = bucketise_results(resolve_results.items())
        new_pkgs = dict(
            compress(pkgs.items(), self.check_pkgs_exist([p.to_defn() for p in pkgs.values()]))
        )

        results = dict.fromkeys(defns, R.PkgAlreadyInstalled()) | resolve_errors

        if dry_run:
            return results | {d: R.PkgInstalled(p, dry_run=True) for d, p in new_pkgs.items()}

        download_results = await gather(
            R.resultify_async_exc(_download_pkg_archive(self.ctx, d, r))
            for d, r in new_pkgs.items()
        )
        archive_paths, download_errors = bucketise_results(zip(new_pkgs, download_results))

        return (
            results
            | download_errors
            | {
                d: await R.resultify_async_exc(
                    _install_pkg(self.ctx, new_pkgs[d], a, replace_folders=replace_folders)
                )
                for d, a in archive_paths.items()
            }
        )

    @_with_lock(_MUTATE_PKGS_LOCK)
    async def update(
        self, defns: Sequence[Defn] | Literal['all'], *, dry_run: bool = False
    ) -> Mapping[Defn, R.AnyResult[R.PkgInstalled | R.PkgUpdated]]:
        "Update installed packages from a definition list."

        if defns == 'all':
            defns_to_pkgs = {p.to_defn(): p for p in self.get_pkgs(defns) if p}
            defns = list(defns_to_pkgs)

            resolve_defns = {d: d for d in defns_to_pkgs}

        else:
            defns_to_pkgs = {d: p for d, p in zip(defns, self.get_pkgs(defns)) if p}

            resolve_defns = {
                # Attach the source ID to each ``Defn`` from the
                # corresponding installed package.  Using the ID has the benefit
                # of resolving installed-but-renamed packages - the slug is
                # transient but the ID isn't
                attrs.evolve(d, id=p.id) if d.strategies.initialised else p.to_defn(): d
                for d, p in defns_to_pkgs.items()
            }

        resolve_results = await self.resolve(resolve_defns, with_deps=True)
        pkgs, resolve_errors = bucketise_results(
            # Discard the reconstructed ``Defn``s
            (resolve_defns.get(d) or d, r)
            for d, r in resolve_results.items()
        )

        async def should_update_pkg(old_pkg: pkg_models.Pkg, new_pkg: pkg_models.Pkg):
            return old_pkg.version != new_pkg.version or not await _check_installed_pkg_integrity(
                self.ctx, old_pkg
            )

        updatables = {
            d: (o, n)
            for d, n in pkgs.items()
            for o in (defns_to_pkgs.get(d),)
            if not o or await should_update_pkg(o, n)
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
            R.resultify_async_exc(_download_pkg_archive(self.ctx, d, n))
            for d, (_, n) in updatables.items()
        )
        archive_paths, download_errors = bucketise_results(zip(updatables, download_results))

        return (
            results
            | download_errors
            | {
                d: await R.resultify_async_exc(
                    _update_pkg(self.ctx, o, n, a)
                    if o
                    else _install_pkg(self.ctx, n, a, replace_folders=False)
                )
                for d, a in archive_paths.items()
                for o, n in (updatables[d],)
            }
        )

    @_with_lock(_MUTATE_PKGS_LOCK)
    async def remove(
        self, defns: Sequence[Defn], *, keep_folders: bool
    ) -> Mapping[Defn, R.AnyResult[R.PkgRemoved]]:
        "Remove packages by their definition."
        return {
            d: (
                await R.resultify_async_exc(_remove_pkg(self.ctx, p, keep_folders=keep_folders))
                if p
                else R.PkgNotInstalled()
            )
            for d, p in zip(defns, self.get_pkgs(defns))
        }

    @_with_lock(_MUTATE_PKGS_LOCK)
    async def pin(self, defns: Sequence[Defn]) -> Mapping[Defn, R.AnyResult[R.PkgInstalled]]:
        """Pin and unpin installed packages.

        instawow does not have true pinning.  This flips ``Strategy.VersionEq``
        on for installed packages from sources that support it.
        The net effect is the same as if the package
        had been reinstalled with the ``VersionEq`` strategy.
        """

        async def pin(defn: Defn, pkg: pkg_models.Pkg | None) -> R.PkgInstalled:
            resolver = self.ctx.resolvers.get(defn.source)
            if resolver is None:
                raise R.PkgSourceInvalid
            elif Strategy.VersionEq not in resolver.metadata.strategies:
                raise R.PkgStrategiesUnsupported({Strategy.VersionEq})

            if not pkg:
                raise R.PkgNotInstalled

            version = defn.strategies.version_eq
            if version and pkg.version != version:
                R.PkgFilesNotMatching(defn.strategies)

            version_eq = version is not None

            with (
                self.ctx.database.connect() as connection,
                self.ctx.database.transact(connection) as transaction,
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
            d: await R.resultify_async_exc(pin(d, p)) for d, p in zip(defns, self.get_pkgs(defns))
        }
