from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Never

from typing_extensions import TypedDict
from yarl import URL

from instawow.wow_installations import to_flavourful_enum

from .. import config_ctx, http_ctx
from .._utils.web import as_plain_text_data_url
from ..definitions import ChangelogFormat, Defn, SourceMetadata, Strategy
from ..resolvers import (
    AccessToken,
    BaseResolver,
    HeadersIntent,
    PkgCandidate,
)
from ..results import PkgFilesNotMatching, PkgNonexistent


class _WagoStability(StrEnum):
    "https://addons.wago.io/api/data/game"

    Stable = 'stable'
    Beta = 'beta'
    Alpha = 'alpha'


class _WagoGameVersion(StrEnum):
    Retail = 'retail'
    VanillaClassic = 'classic'
    WrathClassic = 'wotlk'
    CataClassic = 'cata'
    MistsClassic = 'mop'


class _WagoAddon(TypedDict):
    "``/addons/{id}``"

    id: str
    slug: str
    display_name: str  # Eq to ``WagoRecentAddon.name``
    thumbnail_image: str | None  # Eq to ``WagoRecentAddon.thumbnail``
    summary: str
    description: str  # Long description
    website: str  # Author website
    gallery: list[str]
    authors: list[str]
    download_count: int
    website_url: str  # Page on Wago
    recent_release: dict[_WagoStability, _WagoAddonRelease] | list[Never]


class _WagoAddonRelease(TypedDict):
    label: str  # Version
    supported_retail_patch: str | None  # e.g. "9.2.5"
    supported_classic_patch: str | None
    supported_wotlk_patch: str | None
    changelog: str
    stability: _WagoStability
    created_at: str  # ISO date-time
    download_link: str


class WagoAddonsResolver(BaseResolver):
    metadata = SourceMetadata(
        id='wago',
        name='Wago Addons',
        strategies=frozenset({Strategy.AnyReleaseType}),
        changelog_format=ChangelogFormat.Markdown,
        addon_toc_key='X-Wago-ID',
    )

    __wago_external_api_url = URL('https://addons.wago.io/api/external')

    @AccessToken
    def access_token():
        return config_ctx.config().global_config.access_tokens.wago_addons, True

    def get_alias_from_url(self, url: URL):
        if url.host == 'addons.wago.io' and len(url.parts) > 2 and url.parts[1] == 'addons':
            return url.parts[2]

    def make_request_headers(self, intent: HeadersIntent | None = None):
        return {'Authorization': f'Bearer {self.access_token.get()}'}

    async def resolve_one(self, defn: Defn, metadata: None):
        async with http_ctx.web_client().get(
            (self.__wago_external_api_url / 'addons' / defn.alias).with_query(
                game_version=to_flavourful_enum(config_ctx.config().track, _WagoGameVersion)
            ),
            expire_after=timedelta(minutes=5),
            headers=self.make_request_headers(),
        ) as response:
            if response.status == 404:
                raise PkgNonexistent
            response.raise_for_status()

            addon_metadata: _WagoAddon = await response.json()

        recent_releases = dict(addon_metadata['recent_release'])
        if not defn.strategies[Strategy.AnyReleaseType] and recent_releases.get(
            _WagoStability.Stable
        ):
            recent_releases = {_WagoStability.Stable: recent_releases[_WagoStability.Stable]}

        try:
            file_date, file = max(
                (datetime.fromisoformat(f['created_at']), f) for f in recent_releases.values()
            )
        except ValueError:
            raise PkgFilesNotMatching(defn.strategies)

        return PkgCandidate(
            id=addon_metadata['id'],
            slug=addon_metadata['slug'],
            name=addon_metadata['display_name'],
            description=addon_metadata['summary'],
            url=addon_metadata['website_url'],
            download_url=file['download_link'],
            date_published=file_date,
            version=file['label'],
            changelog_url=as_plain_text_data_url(file['changelog']),
        )
