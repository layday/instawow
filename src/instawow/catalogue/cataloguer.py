from __future__ import annotations

from collections.abc import Set
from datetime import datetime
from functools import cached_property
from types import SimpleNamespace
from typing import Any, Self

import attrs
import cattrs
import cattrs.preconf.json

from .. import config, config_ctx, http, http_ctx
from .._utils.attrs import fauxfrozen
from .._utils.iteration import bucketise
from .._utils.text import normalise_names
from ..wow_installations import Flavour

CATALOGUE_VERSION = 7
COMPUTED_CATALOGUE_VERSION = 4


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
    async def collate(cls, start_date: datetime | None) -> Self:
        global_config = config.GlobalConfig.from_values(env=True)

        @config_ctx.config.set  # pyright: ignore[reportArgumentType]
        def _():
            return SimpleNamespace(global_config=global_config)

        async with http.init_web_client(global_config.http_cache_dir) as web_client:
            http_ctx.web_client.set(web_client)

            entries = [e for r in config_ctx.resolvers().values() async for e in r.catalogue()]
            if start_date is not None:
                entries = [e for e in entries if e.last_updated >= start_date]
            return cls(entries=entries)

    def to_json_dict(self) -> Any:
        return _catalogue_converter.unstructure(self)


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
    def keyed_entries(self) -> dict[tuple[str, str], ComputedCatalogueEntry]:
        return {(e.source, e.id): e for e in self.entries}
