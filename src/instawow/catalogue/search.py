from __future__ import annotations

from collections.abc import Callable, Iterator, Set
from datetime import datetime
from typing import Literal

from .. import config_ctx
from .._utils.iteration import bucketise
from .._utils.text import normalise_names
from ..wow_installations import to_flavour
from . import synchronise as synchronise_catalogue
from .cataloguer import CatalogueEntry

_normalise_search_terms = normalise_names('')


async def search(
    search_terms: str,
    *,
    limit: int,
    sources: Set[str] = frozenset(),
    prefer_source: str | None = None,
    start_date: datetime | None = None,
    filter_installed: Literal[
        'ident', 'include_only', 'exclude', 'exclude_from_all_sources'
    ] = 'ident',
) -> list[CatalogueEntry]:
    "Search the catalogue for packages by name."
    import rapidfuzz

    resolvers = config_ctx.resolvers()
    catalogue = await synchronise_catalogue()

    ew = 0.5
    dw = 1 - ew

    threshold = 0 if search_terms == '*' else 70

    if sources:
        unknown_sources = sources - resolvers.keys()
        if unknown_sources:
            raise ValueError(f'Unknown sources: {", ".join(unknown_sources)}')

    if prefer_source and prefer_source not in resolvers:
        raise ValueError(f'Unknown preferred source: {prefer_source}')

    def get_installed_pkg_keys():
        from ..pkg_db import use_tuple_factory

        with (
            config_ctx.database() as connection,
            use_tuple_factory(connection) as cursor,
        ):
            return cursor.execute('SELECT source, id FROM pkg').fetchall()

    def make_filter_fns() -> Iterator[Callable[[CatalogueEntry], bool]]:
        flavour = to_flavour(config_ctx.config().track)
        yield lambda e: flavour in e.game_flavours

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
