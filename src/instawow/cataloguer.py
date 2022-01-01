from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
import typing
from typing import Any

from pydantic import BaseModel

from . import manager
from .config import Flavour
from .utils import bucketise, cached_property, normalise_names


class _SameAs(BaseModel):
    source: str
    id: str


class BaseCatatalogueEntry(BaseModel):
    source: str
    id: str
    slug: str = ''
    name: str
    url: str
    game_flavours: typing.Set[Flavour]
    download_count: int
    last_updated: datetime
    folders: typing.List[typing.Set[str]] = []
    same_as: typing.List[_SameAs] = []


class CatalogueEntry(BaseCatatalogueEntry):
    normalised_name: str
    derived_download_score: float


class BaseCatalogue(BaseModel, json_encoders={set: sorted}):
    version = 5
    entries: typing.List[BaseCatatalogueEntry]

    @classmethod
    async def collate(cls, start_date: datetime | None):
        async with manager.init_web_client() as web_client:
            entries = [e for r in manager.Manager.RESOLVERS async for e in r.catalogue(web_client)]
            if start_date is not None:
                entries = [e for e in entries if e.last_updated >= start_date]
            return cls(entries=entries)


class Catalogue(BaseModel, keep_untouched=(cached_property,)):
    version = 1
    entries: typing.List[CatalogueEntry]
    curse_slugs: typing.Dict[str, str]

    @classmethod
    def from_base_catalogue(cls, raw_base_catalogue: Sequence[Any], start_date: datetime | None):
        normalise = normalise_names('')

        base_entries = BaseCatalogue.parse_obj(raw_base_catalogue).entries
        if start_date is not None:
            base_entries = [e for e in base_entries if e.last_updated >= start_date]

        most_downloads_per_source = {
            s: max(e.download_count for e in i)
            for s, i in bucketise(base_entries, key=lambda e: e.source).items()
        }
        same_as_from_github = {
            (s.source, s.id): [
                _SameAs(source=e.source, id=e.id),
                *(i for i in e.same_as if i.source != s.source),
            ]
            for e in base_entries
            if e.source == 'github' and e.same_as
            for s in e.same_as
        }
        entries = [
            CatalogueEntry.parse_obj(
                {
                    **e.__dict__,
                    'same_as': e.same_as
                    if e.source == 'github'
                    else (same_as_from_github.get((e.source, e.id)) or e.same_as),
                    'normalised_name': normalise(e.name),
                    'derived_download_score': 0
                    if e.source == 'github'
                    else e.download_count / most_downloads_per_source[e.source],
                }
            )
            for e in base_entries
        ]
        return cls(
            entries=entries,
            curse_slugs={e.slug: e.id for e in entries if e.source == 'curse'},
        )

    @cached_property
    def keyed_entries(self) -> dict[tuple[str, str], CatalogueEntry]:
        return {(e.source, e.id): e for e in self.entries}
