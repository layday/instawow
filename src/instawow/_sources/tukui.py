from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

from loguru import logger
from typing_extensions import TypedDict
from yarl import URL

from .. import pkg_models
from .. import results as R
from ..catalogue.cataloguer import CatalogueEntry
from ..common import ChangelogFormat, Defn, Flavour, FlavourVersionRange, SourceMetadata
from ..http import ClientSessionType
from ..resolvers import BaseResolver


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
    screenshort_url: str
    directories: list[str]


class TukuiResolver(BaseResolver):
    metadata = SourceMetadata(
        id='tukui',
        name='Tukui',
        strategies=frozenset(),
        changelog_format=ChangelogFormat.Markdown,
        addon_toc_key='X-Tukui-ProjectID',
    )
    requires_access_token = None

    _api_url = URL('https://api.tukui.org/v1/')

    async def resolve_one(self, defn: Defn, metadata: None) -> pkg_models.Pkg:
        async with self._manager_ctx.web_client.get(
            self._api_url / 'addon' / defn.alias,
            expire_after=timedelta(minutes=5),
        ) as response:
            if response.status == 404:
                raise R.PkgNonexistent
            response.raise_for_status()

            ui_metadata: _TukuiAddon = await response.json()

        if not any(
            Flavour.from_flavour_keyed_enum(r) is self._manager_ctx.config.game_flavour
            for g in ui_metadata['patch']
            for r in (FlavourVersionRange.from_version_string(g),)
            if r
        ):
            raise R.PkgFilesNotMatching(defn.strategies)

        return pkg_models.Pkg(
            source=self.metadata.id,
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
            options=pkg_models.PkgOptions.from_strategy_values(defn.strategies),
        )

    @classmethod
    async def catalogue(cls, web_client: ClientSessionType) -> AsyncIterator[CatalogueEntry]:
        url = cls._api_url / 'addons'
        logger.debug(f'retrieving {url}')

        async with web_client.get(url, raise_for_status=True) as response:
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
                    for r in (FlavourVersionRange.from_version_string(g),)
                    if r
                ),
                download_count=1,
                last_updated=datetime.fromisoformat(item['last_update']).replace(
                    tzinfo=timezone.utc
                ),
                folders=[frozenset(item['directories'])],
            )
