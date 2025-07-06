from __future__ import annotations

from datetime import UTC, datetime, timedelta

from typing_extensions import TypedDict
from yarl import URL

from .. import config_ctx, http_ctx
from .._logging import logger
from ..definitions import ChangelogFormat, Defn, SourceMetadata
from ..resolvers import BaseResolver, CatalogueEntryCandidate, PkgCandidate
from ..results import PkgFilesNotMatching, PkgNonexistent
from ..wow_installations import FlavourVersions, to_flavour, to_flavour_versions


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

    __api_url = URL('https://api.tukui.org/v1/')

    async def resolve_one(self, defn: Defn, metadata: None):
        async with http_ctx.web_client().get(
            self.__api_url / 'addon' / defn.alias,
            expire_after=timedelta(minutes=5),
        ) as response:
            if response.status == 404:
                raise PkgNonexistent
            response.raise_for_status()

            ui_metadata: _TukuiAddon = await response.json()

        flavour_versions = to_flavour_versions(config_ctx.config().track)
        if not any(
            FlavourVersions.from_version_string(p) is flavour_versions
            for p in ui_metadata['patch']
        ):
            raise PkgFilesNotMatching(defn.strategies)

        return PkgCandidate(
            id=str(ui_metadata['id']),
            slug=ui_metadata['slug'],
            name=ui_metadata['name'],
            description=ui_metadata['small_desc'],
            url=ui_metadata['web_url'],
            download_url=ui_metadata['url'],
            date_published=datetime.fromisoformat(ui_metadata['last_update']).replace(tzinfo=UTC),
            version=ui_metadata['version'],
            changelog_url=(
                # The changelog URL is not versioned - add fragment to allow caching.
                str(URL(ui_metadata['changelog_url']).with_fragment(ui_metadata['version']))
            ),
        )

    async def catalogue(self):
        url = self.__api_url / 'addons'
        logger.debug(f'Retrieving {url}')

        async with http_ctx.web_client().get(url, raise_for_status=True) as response:
            items: list[_TukuiAddon] = await response.json()

        for item in items:
            yield CatalogueEntryCandidate(
                id=str(item['id']),
                slug=item['slug'],
                name=item['name'],
                url=item['web_url'],
                game_flavours=frozenset(
                    to_flavour(f)
                    for p in item['patch']
                    for f in (FlavourVersions.from_version_string(p),)
                    if f
                ),
                download_count=1,
                last_updated=datetime.fromisoformat(item['last_update']).replace(tzinfo=UTC),
                folders=[frozenset(item['directories'])],
            )
