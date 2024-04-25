from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Set
from datetime import datetime
from functools import cached_property
from typing import Any, Protocol

import attrs
import cattrs
import cattrs.preconf.json
from typing_extensions import Self

from .. import http
from .._utils.compat import fauxfrozen
from .._utils.iteration import bucketise
from .._utils.text import normalise_names
from ..wow_installations import Flavour

CATALOGUE_VERSION = 7
COMPUTED_CATALOGUE_VERSION = 4


catalogue_converter = cattrs.Converter(
    unstruct_collection_overrides={
        Set: sorted,
    }
)
cattrs.preconf.json.configure_converter(catalogue_converter)

_normalise_name = normalise_names('')


class _CatalogueFn(Protocol):  # pragma: no cover
    def __call__(self, web_client: http.ClientSessionType) -> AsyncIterator[CatalogueEntry]: ...


@fauxfrozen(kw_only=True)
class AddonKey:
    source: str
    id: str


@fauxfrozen(kw_only=True)
class CatalogueEntry(AddonKey):
    slug: str = ''
    name: str
    url: str
    game_flavours: frozenset[Flavour]
    download_count: int
    last_updated: datetime
    folders: list[frozenset[str]] = attrs.field(factory=list)
    same_as: list[AddonKey] = attrs.field(factory=list)


@fauxfrozen(kw_only=True)
class ComputedCatalogueEntry(CatalogueEntry):
    normalised_name: str
    derived_download_score: float


@fauxfrozen(kw_only=True)
class Catalogue:
    version: int = CATALOGUE_VERSION
    entries: list[CatalogueEntry]

    @classmethod
    async def collate(
        cls, catalogue_fns: Iterable[_CatalogueFn], start_date: datetime | None
    ) -> Self:
        async with http.init_web_client(None) as web_client:
            entries = [e for r in catalogue_fns async for e in r(web_client)]
            if start_date is not None:
                entries = [e for e in entries if e.last_updated >= start_date]
            return cls(entries=entries)


@fauxfrozen(kw_only=True)
class ComputedCatalogue:
    version: int = COMPUTED_CATALOGUE_VERSION
    entries: list[ComputedCatalogueEntry]

    @classmethod
    def from_base_catalogue(cls, unstructured_base_catalogue: dict[str, Any]) -> Self:
        from .._sources.github import GithubResolver

        normalise_name = _normalise_name

        base_entries = unstructured_base_catalogue['entries']

        most_downloads_per_source = {
            s: max(e['download_count'] for e in i)
            for s, i in bucketise(base_entries, key=lambda e: e['source']).items()
        }
        same_as_from_github = {
            (s['source'], s['id']): [
                e,
                *(i for i in e['same_as'] if i['source'] != s['source']),
            ]
            for e in base_entries
            if e['source'] == GithubResolver.metadata.id and e['same_as']
            for s in e['same_as']
        }

        return catalogue_converter.structure(
            {
                'entries': (
                    e
                    | {
                        'same_as': e['same_as']
                        if e['source'] == GithubResolver.metadata.id
                        else (same_as_from_github.get((e['source'], e['id'])) or e['same_as']),
                        'normalised_name': normalise_name(e['name']),
                        'derived_download_score': e['download_count']
                        / most_downloads_per_source[e['source']],
                    }
                    for e in base_entries
                ),
            },
            cls,
        )

    @cached_property
    def keyed_entries(self) -> dict[tuple[str, str], ComputedCatalogueEntry]:
        return {(e.source, e.id): e for e in self.entries}
