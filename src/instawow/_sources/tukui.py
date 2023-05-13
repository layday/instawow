from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from typing import Literal

from loguru import logger
from typing_extensions import TypedDict
from yarl import URL

from .. import models
from .. import results as R
from ..cataloguer import BaseCatalogueEntry
from ..common import ChangelogFormat, Defn, Flavour, SourceMetadata
from ..http import ClientSessionType
from ..resolvers import BaseResolver


class _TukuiUi(TypedDict):
    author: str
    category: str
    changelog: str
    donate_url: str
    downloads: int
    git: str
    id: Literal[-1, -2]  # -1 is Tukui and -2 ElvUI
    lastdownload: str
    lastupdate: str  # ISO date and no tz, e.g. '2020-02-02'
    name: str
    patch: str | None
    screenshot_url: str
    small_desc: str
    ticket: str
    url: str
    version: str
    web_url: str


class TukuiResolver(BaseResolver):
    metadata = SourceMetadata(
        id='tukui',
        name='Tukui',
        strategies=frozenset(),
        changelog_format=ChangelogFormat.Html,
        addon_toc_key='X-Tukui-ProjectID',
    )
    requires_access_token = None

    # There's also a ``/client-api.php`` endpoint which is apparently
    # used by the Tukui client itself to check for UI suite updates only.
    # The response body appears to be identical to ``/api.php``
    _api_url = URL('https://www.tukui.org/api.php')

    _KNOWN_ALIASES = {
        '-2': 'elvui',
        'elvui': 'elvui',
        '-1': 'tukui',
        'tukui': 'tukui',
    }

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if url.host == 'www.tukui.org' and url.path == '/download.php':
            return url.query.get('ui')

    async def resolve_one(self, defn: Defn, metadata: None) -> models.Pkg:
        ui_slug = self._KNOWN_ALIASES.get(defn.alias)
        if ui_slug is None:
            raise R.PkgNonexistent

        async with self._manager.web_client.get(
            self._api_url.with_query({'ui': ui_slug}),
            expire_after=timedelta(minutes=5),
            raise_for_status=True,
        ) as response:
            ui_metadata: _TukuiUi = await response.json(content_type=None)  # text/html

        return models.Pkg(
            source=self.metadata.id,
            id=str(ui_metadata['id']),
            slug=ui_slug,
            name=ui_metadata['name'],
            description=ui_metadata['small_desc'],
            url=ui_metadata['web_url'],
            download_url=ui_metadata['url'],
            date_published=datetime.fromisoformat(ui_metadata['lastupdate']).replace(
                tzinfo=timezone.utc
            ),
            version=ui_metadata['version'],
            changelog_url=(
                # The changelog URL is not versioned - add fragment to allow caching.
                str(URL(ui_metadata['changelog']).with_fragment(ui_metadata['version']))
            ),
            options=models.PkgOptions.from_strategy_values(defn.strategies),
        )

    @classmethod
    async def catalogue(cls, web_client: ClientSessionType) -> AsyncIterator[BaseCatalogueEntry]:
        for ui_slug in set(cls._KNOWN_ALIASES.values()):
            url = cls._api_url.with_query({'ui': ui_slug})
            logger.debug(f'retrieving {url}')
            async with web_client.get(url, raise_for_status=True) as response:
                item: _TukuiUi = await response.json(content_type=None)  # text/html

            yield BaseCatalogueEntry(
                source=cls.metadata.id,
                id=str(item['id']),
                name=item['name'],
                url=item['web_url'],
                game_flavours=frozenset(Flavour),
                # Split Tukui and ElvUI downloads evenly between them.
                # They both have the exact same number of downloads so
                # I'm assuming they're being counted together.
                download_count=int(item['downloads']) // 2,
                last_updated=datetime.fromisoformat(item['lastupdate']).replace(
                    tzinfo=timezone.utc
                ),
            )
