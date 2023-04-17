from __future__ import annotations

from collections.abc import Set
from datetime import datetime
from functools import cached_property

from attrs import asdict, frozen
from cattrs import Converter
from cattrs.preconf.json import configure_converter
from typing_extensions import Self

from .config import Flavour
from .utils import bucketise, normalise_names

BASE_CATALOGUE_VERSION = 7
CATALOGUE_VERSION = 4


catalogue_converter = Converter(
    unstruct_collection_overrides={
        Set: sorted,
    }
)
configure_converter(catalogue_converter)


@frozen(kw_only=True)
class CatalogueSameAs:
    source: str
    id: str


@frozen(kw_only=True)
class BaseCatalogueEntry:
    source: str
    id: str
    slug: str = ''
    name: str
    url: str
    game_flavours: frozenset[Flavour]
    download_count: int
    last_updated: datetime
    folders: list[frozenset[str]] = []
    same_as: list[CatalogueSameAs] = []


@frozen(kw_only=True)
class CatalogueEntry(BaseCatalogueEntry):
    normalised_name: str
    derived_download_score: float


@frozen(kw_only=True)
class BaseCatalogue:
    version: int = BASE_CATALOGUE_VERSION
    entries: list[BaseCatalogueEntry]

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
class Catalogue:
    version: int = CATALOGUE_VERSION
    entries: list[CatalogueEntry]
    curse_slugs: dict[str, str]

    @classmethod
    def from_base_catalogue(
        cls, unstructured_base_catalogue: object, start_date: datetime | None
    ) -> Self:
        from ._sources.cfcore import CfCoreResolver
        from ._sources.github import GithubResolver

        normalise = normalise_names('')

        base_entries = catalogue_converter.structure(
            unstructured_base_catalogue, BaseCatalogue
        ).entries
        if start_date is not None:
            base_entries = [e for e in base_entries if e.last_updated >= start_date]

        most_downloads_per_source = {
            s: max(e.download_count for e in i)
            for s, i in bucketise(base_entries, key=lambda e: e.source).items()
        }
        same_as_from_github = {
            (s.source, s.id): [
                CatalogueSameAs(source=e.source, id=e.id),
                *(i for i in e.same_as if i.source != s.source),
            ]
            for e in base_entries
            if e.source == GithubResolver.metadata.id and e.same_as
            for s in e.same_as
        }
        entries = [
            CatalogueEntry(
                **asdict(e, filter=lambda a, _: a.name != 'same_as'),
                same_as=e.same_as
                if e.source == GithubResolver.metadata.id
                else (same_as_from_github.get((e.source, e.id)) or e.same_as),
                normalised_name=normalise(e.name),
                derived_download_score=0
                if e.source == GithubResolver.metadata.id
                else e.download_count / most_downloads_per_source[e.source],
            )
            for e in base_entries
        ]
        return cls(
            entries=entries,
            curse_slugs={e.slug: e.id for e in entries if e.source == CfCoreResolver.metadata.id},
        )

    @cached_property
    def keyed_entries(self) -> dict[tuple[str, str], CatalogueEntry]:
        return {(e.source, e.id): e for e in self.entries}
