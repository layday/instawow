from __future__ import annotations

from datetime import datetime
import typing

from attrs import asdict, frozen
from cattrs import GenConverter
from cattrs.preconf.json import configure_converter

from . import manager
from .config import Flavour
from .utils import bucketise, cached_property, normalise_names

catalogue_converter = GenConverter(
    unstruct_collection_overrides={
        # TODO: Replace with ``collections.abc.Set``
        frozenset: sorted,
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
    game_flavours: typing.FrozenSet[Flavour]
    download_count: int
    last_updated: datetime
    folders: typing.List[typing.FrozenSet[str]] = []
    same_as: typing.List[CatalogueSameAs] = []


@frozen(kw_only=True)
class CatalogueEntry(BaseCatalogueEntry):
    normalised_name: str
    derived_download_score: float


@frozen(kw_only=True)
class BaseCatalogue:
    version: int = 5
    entries: typing.List[BaseCatalogueEntry]

    @classmethod
    async def collate(cls, start_date: datetime | None):
        async with manager.init_web_client() as web_client:
            entries = [e for r in manager.Manager.RESOLVERS async for e in r.catalogue(web_client)]
            if start_date is not None:
                entries = [e for e in entries if e.last_updated >= start_date]
            return cls(entries=entries)


@frozen(kw_only=True, slots=False)
class Catalogue:
    version: int = 3
    entries: typing.List[CatalogueEntry]
    curse_slugs: typing.Dict[str, str]

    @classmethod
    def from_base_catalogue(cls, unstructured_base_catalogue: object, start_date: datetime | None):
        from .resolvers import CfCoreResolver, GithubResolver

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
                **{
                    **asdict(e),
                    'same_as': e.same_as
                    if e.source == GithubResolver.metadata.id
                    else (same_as_from_github.get((e.source, e.id)) or e.same_as),
                    'normalised_name': normalise(e.name),
                    'derived_download_score': 0
                    if e.source == GithubResolver.metadata.id
                    else e.download_count / most_downloads_per_source[e.source],
                }
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
