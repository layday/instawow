from __future__ import annotations

from collections.abc import Set
from datetime import datetime
from functools import cached_property
from typing import Any, Self

import cattrs
import cattrs.preconf.json

from .. import config_ctx
from .._utils.attrs import fauxfrozen
from .._utils.iteration import bucketise
from .._utils.text import normalise_names
from ..wow_installations import Flavour

CATALOGUE_VERSION = 8


_catalogue_converter = cattrs.Converter(
    unstruct_collection_overrides={
        Set: sorted,
    }
)
cattrs.preconf.json.configure_converter(_catalogue_converter)

_normalise_name = normalise_names('')


@fauxfrozen(kw_only=True)
class AddonKey:
    source: str
    id: str


@fauxfrozen(kw_only=True)
class CatalogueEntry(AddonKey):
    slug: str
    name: str
    url: str
    game_flavours: frozenset[Flavour]
    download_count: int
    last_updated: datetime
    folders: list[frozenset[str]]
    same_as: list[AddonKey]
    normalised_name: str
    derived_download_score: float


async def collate(start_date: datetime | None) -> dict[str, Any]:
    return _catalogue_converter.unstructure(
        {
            'version': CATALOGUE_VERSION,
            'entries': [
                {
                    'source': r.metadata.id,
                    'slug': '',
                    'folders': [],
                    'same_as': [],
                }
                | e
                for r in config_ctx.resolvers().values()
                async for e in r.catalogue()
                if not start_date or e['last_updated'] >= start_date
            ],
        }
    )


@fauxfrozen(kw_only=True)
class ComputedCatalogue:
    entries: list[CatalogueEntry]

    @classmethod
    def from_base_catalogue(cls, unstructured_base_catalogue: dict[str, Any]) -> Self:
        from .._sources.github import GithubResolver

        normalise_name = _normalise_name

        base_entries = unstructured_base_catalogue['entries']

        most_downloads_per_source = {
            s: max(e['download_count'] for e in i) or 1
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

        return _catalogue_converter.structure(
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
    def keyed_entries(self) -> dict[tuple[str, str], CatalogueEntry]:
        return {(e.source, e.id): e for e in self.entries}
