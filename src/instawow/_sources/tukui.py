from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

from typing_extensions import TypedDict
from yarl import URL

from .. import results as R
from .. import shared_ctx
from .._logging import logger
from ..catalogue.cataloguer import CatalogueEntry
from ..definitions import ChangelogFormat, Defn, SourceMetadata
from ..resolvers import BaseResolver, PkgCandidate
from ..wow_installations import Flavour, FlavourVersionRange


class _TukuiAddon(TypedDict):
    id: int
    slug: str
    author: str
    name: str
    url: str
    version: str
    changelog_url: str
    ticket_url: str
    git_url: str
    patch: list[str]
    last_update: str  # YYYY-MM-DD
    web_url: str
    donate_url: str
    small_desc: str
    desc: str
    screenshort_url: str
    gallery_url: list[str]
    logo_url: str
    logo_square_url: str
    directories: list[str]


class TukuiResolver(BaseResolver):
    metadata = SourceMetadata(
        id='tukui',
        name='Tukui',
        strategies=frozenset(),
        changelog_format=ChangelogFormat.Markdown,
        addon_toc_key='X-Tukui-ProjectID',
    )
    access_token = None

    __api_url = URL('https://api.tukui.org/v1/')

    async def _resolve_one(self, defn: Defn, metadata: None) -> PkgCandidate:
        async with shared_ctx.web_client.get(
            self.__api_url / 'addon' / defn.alias,
            expire_after=timedelta(minutes=5),
        ) as response:
            if response.status == 404:
                raise R.PkgNonexistent
            response.raise_for_status()

            ui_metadata: _TukuiAddon = await response.json()

        wanted_version_range = self._config.game_flavour.to_flavour_keyed_enum(FlavourVersionRange)
        if not any(wanted_version_range.contains(p) for p in ui_metadata['patch']):
            raise R.PkgFilesNotMatching(defn.strategies)

        return PkgCandidate(
            id=str(ui_metadata['id']),
            slug=ui_metadata['slug'],
            name=ui_metadata['name'],
            description=ui_metadata['small_desc'],
            url=ui_metadata['web_url'],
            download_url=ui_metadata['url'],
            date_published=datetime.fromisoformat(ui_metadata['last_update']).replace(
                tzinfo=timezone.utc
            ),
            version=ui_metadata['version'],
            changelog_url=(
                # The changelog URL is not versioned - add fragment to allow caching.
                str(URL(ui_metadata['changelog_url']).with_fragment(ui_metadata['version']))
            ),
        )

    @classmethod
    async def catalogue(cls) -> AsyncIterator[CatalogueEntry]:
        url = cls.__api_url / 'addons'
        logger.debug(f'retrieving {url}')

        async with shared_ctx.web_client.get(url, raise_for_status=True) as response:
            items: list[_TukuiAddon] = await response.json()

        for item in items:
            yield CatalogueEntry(
                source=cls.metadata.id,
                id=str(item['id']),
                slug=item['slug'],
                name=item['name'],
                url=item['web_url'],
                game_flavours=frozenset(
                    Flavour.from_flavour_keyed_enum(r)
                    for g in item['patch']
                    if (r := FlavourVersionRange.from_version(g))
                ),
                download_count=1,
                last_updated=datetime.fromisoformat(item['last_update']).replace(
                    tzinfo=timezone.utc
                ),
                folders=[frozenset(item['directories'])],
            )
