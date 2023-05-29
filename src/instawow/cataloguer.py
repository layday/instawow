from __future__ import annotations

from collections.abc import Set
from datetime import datetime
from functools import cached_property
from typing import Any

from attrs import frozen
from cattrs import Converter
from cattrs.preconf.json import configure_converter
from typing_extensions import Self

from .config import Flavour
from .utils import bucketise, normalise_names

CATALOGUE_VERSION = 7
COMPUTED_CATALOGUE_VERSION = 4


catalogue_converter = Converter(
    unstruct_collection_overrides={
        Set: sorted,
    }
)
configure_converter(catalogue_converter)

_normalise_name = normalise_names('')


@frozen(kw_only=True)
class AddonKey:
    source: str
    id: str


@frozen(kw_only=True)
class CatalogueEntry(AddonKey):
    slug: str = ''
    name: str
    url: str
    game_flavours: frozenset[Flavour]
    download_count: int
    last_updated: datetime
    folders: list[frozenset[str]] = []
    same_as: list[AddonKey] = []


@frozen(kw_only=True)
class ComputedCatalogueEntry(CatalogueEntry):
    normalised_name: str
    derived_download_score: float


@frozen(kw_only=True)
class Catalogue:
    version: int = CATALOGUE_VERSION
    entries: list[CatalogueEntry]

    @classmethod
    async def collate(cls, start_date: datetime | None) -> Self:
        from .http import init_web_client
        from .manager import Manager

        async with init_web_client(None) as web_client:
            entries = [e for r in Manager.RESOLVERS async for e in r.catalogue(web_client)]
            if start_date is not None:
                entries = [e for e in entries if e.last_updated >= start_date]
            return cls(entries=entries)


@frozen(kw_only=True, slots=False)
class ComputedCatalogue:
    version: int = COMPUTED_CATALOGUE_VERSION
    entries: list[ComputedCatalogueEntry]
    curse_slugs: dict[str, str]

    @classmethod
    def from_base_catalogue(cls, unstructured_base_catalogue: dict[str, Any]) -> Self:
        from ._sources.cfcore import CfCoreResolver
        from ._sources.github import GithubResolver

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
                        'derived_download_score': 0
                        if e['source'] == GithubResolver.metadata.id
                        else e['download_count'] / most_downloads_per_source[e['source']],
                    }
                    for e in base_entries
                ),
                'curse_slugs': {
                    e['slug']: e['id']
                    for e in base_entries
                    if e['source'] == CfCoreResolver.metadata.id
                },
            },
            cls,
        )

    @cached_property
    def keyed_entries(self) -> dict[tuple[str, str], ComputedCatalogueEntry]:
        return {(e.source, e.id): e for e in self.entries}
