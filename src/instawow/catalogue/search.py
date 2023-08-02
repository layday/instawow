from __future__ import annotations

from collections.abc import Callable, Iterator, Set
from datetime import datetime
from typing import Literal

from .. import manager_ctx, pkg_db
from ..utils import bucketise, normalise_names
from . import cataloguer

_normalise_search_terms = normalise_names('')


async def search(
    manager_ctx: manager_ctx.ManagerCtx,
    search_terms: str,
    *,
    limit: int,
    sources: Set[str] = frozenset(),
    prefer_source: str | None = None,
    start_date: datetime | None = None,
    filter_installed: Literal[
        'ident', 'include_only', 'exclude', 'exclude_from_all_sources'
    ] = 'ident',
) -> list[cataloguer.ComputedCatalogueEntry]:
    "Search the catalogue for packages by name."
    import rapidfuzz
    import sqlalchemy as sa

    catalogue = await manager_ctx.synchronise()

    ew = 0.5
    dw = 1 - ew

    threshold = 0 if search_terms == '*' else 70

    if sources:
        unknown_sources = sources - manager_ctx.resolvers.keys()
        if unknown_sources:
            raise ValueError(f'Unknown sources: {", ".join(unknown_sources)}')

    if prefer_source and prefer_source not in manager_ctx.resolvers:
        raise ValueError(f'Unknown preferred source: {prefer_source}')

    def get_installed_pkg_keys():
        with manager_ctx.database.connect() as connection:
            return (
                connection.execute(sa.select(pkg_db.pkg.c.source, pkg_db.pkg.c.id)).tuples().all()
            )

    def make_filter_fns() -> Iterator[Callable[[cataloguer.ComputedCatalogueEntry], bool]]:
        yield lambda e: manager_ctx.config.game_flavour in e.game_flavours

        if sources:
            yield lambda e: e.source in sources

        if start_date is not None:
            start_date_ = start_date
            yield lambda e: e.last_updated >= start_date_

        if filter_installed in {'exclude', 'exclude_from_all_sources'}:
            installed_pkg_keys = set(get_installed_pkg_keys())
            if filter_installed == 'exclude_from_all_sources':
                installed_pkg_keys |= {
                    (s.source, s.id)
                    for k in installed_pkg_keys
                    for e in (catalogue.keyed_entries.get(k),)
                    if e
                    for s in e.same_as
                }

            yield lambda e: (e.source, e.id) not in installed_pkg_keys

    filter_fns = list(make_filter_fns())

    entries = catalogue.entries

    if prefer_source:
        entries = (e for e in entries if not any(s.source == prefer_source for s in e.same_as))

    if filter_installed == 'include_only':
        installed_pkg_keys = get_installed_pkg_keys()
        entries = (e for k in installed_pkg_keys for e in (catalogue.keyed_entries.get(k),) if e)

    s = _normalise_search_terms(search_terms)

    tokens_to_entries = bucketise(
        ((e.normalised_name, e) for e in entries if all(f(e) for f in filter_fns)),
        key=lambda v: v[0],
    )
    matches = rapidfuzz.process.extract(
        s,
        list(tokens_to_entries),
        scorer=rapidfuzz.fuzz.WRatio,
        limit=limit * 2,
        score_cutoff=threshold,
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
