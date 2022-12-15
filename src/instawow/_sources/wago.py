from __future__ import annotations

from collections.abc import Collection, Iterable
from datetime import timedelta
from typing import Literal, NoReturn

import iso8601
from typing_extensions import TypedDict
from yarl import URL

from .. import models
from .. import results as R
from ..common import AddonHashMethod, ChangelogFormat, Defn, SourceMetadata, Strategy
from ..http import make_generic_progress_ctx
from ..resolvers import BaseResolver, HeadersIntent, TFolderHashCandidate
from ..utils import StrEnum, as_plain_text_data_url, run_in_thread

_WagoStability = Literal['stable', 'beta', 'alpha']


class _WagoGameVersion(StrEnum):
    retail = 'retail'
    vanilla_classic = 'classic'
    classic = 'wotlk'


class _WagoMatchRequest(TypedDict):
    "``/addons/_match``"
    game_version: _WagoGameVersion
    addons: list[_WagoMatchRequestAddon]


class _WagoMatchRequestAddon(TypedDict):
    name: str
    hash: str


class _WagoMatches(TypedDict):
    "``/addons/_match``"
    addons: list[_WagoMatchingAddon | None]


class _WagoMatchingAddon(TypedDict):
    id: str
    name: str  # Eq to ``WagoAddon.display_name``
    authors: list[str]
    website_url: str  # Page on Wago
    thumbnail: str | None
    matched_release: _WagoRecentAddonRelease
    modules: dict[str, _WagoAddonModule]  # Add-on folders
    cf: str | None
    wowi: str | None
    wago: str  # Same as ``id``
    recent_releases: dict[_WagoStability, _WagoRecentAddonRelease]


class _WagoRecentAddonRelease(TypedDict):
    id: str
    label: str  # Version
    patch: str  # e.g. "9.2.5"
    created_at: str  # ISO date-time
    link: str


class _WagoAddonModule(TypedDict):
    hash: str


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
    recent_release: dict[_WagoStability, _WagoAddonRelease] | list[NoReturn]


class _WagoAddonRelease(TypedDict):
    label: str  # Version
    supported_retail_patch: str | None  # e.g. "9.2.5"
    supported_classic_patch: str | None
    supported_wotlk_patch: str | None
    changelog: str
    stability: _WagoStability
    created_at: str  # ISO date-time
    download_link: str


class WagoResolver(BaseResolver):
    metadata = SourceMetadata(
        id='wago',
        name='Wago Addons',
        strategies=frozenset({Strategy.any_release_type}),
        changelog_format=ChangelogFormat.markdown,
        addon_toc_key='X-Wago-ID',
    )
    requires_access_token = 'wago_addons'

    _wago_external_api_url = URL('https://addons.wago.io/api/external')

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if url.host == 'addons.wago.io' and len(url.parts) > 2 and url.parts[1] == 'addons':
            return url.parts[2]

    async def make_request_headers(self, intent: HeadersIntent | None = None) -> dict[str, str]:
        maybe_access_token = self._get_access_token(self._manager.config.global_config)
        if maybe_access_token is None:
            raise ValueError(f'{self.metadata.name} access token is not configured')
        return {'Authorization': f'Bearer {maybe_access_token}'}

    async def resolve_one(self, defn: Defn, metadata: None) -> models.Pkg:
        wago_game_version = self._manager.config.game_flavour.to_flavour_keyed_enum(
            _WagoGameVersion
        )

        async with self._manager.web_client.get(
            (self._wago_external_api_url / 'addons' / defn.alias).with_query(
                game_version=wago_game_version.value,
            ),
            expire_after=timedelta(minutes=5),
            headers=await self.make_request_headers(),
        ) as response:
            if response.status == 404:
                raise R.PkgNonexistent
            response.raise_for_status()

            addon_metadata: _WagoAddon = await response.json()

        recent_releases = dict(addon_metadata['recent_release'])
        if not defn.strategies.any_release_type:
            files = filter(None, (recent_releases.get('stable'),))
        else:
            files = recent_releases.values()

        matching_file = max(
            ((iso8601.parse_date(f['created_at']), f) for f in files), default=None
        )
        if matching_file is None:
            raise R.PkgFilesMissing
        else:
            file_date, file = matching_file

        return models.Pkg(
            source=self.metadata.id,
            id=addon_metadata['id'],
            slug=addon_metadata['slug'],
            name=addon_metadata['display_name'],
            description=addon_metadata['summary'],
            url=addon_metadata['website_url'],
            download_url=file['download_link'],
            date_published=file_date,
            version=file['label'],
            changelog_url=as_plain_text_data_url(file['changelog']),
            options=models.PkgOptions.from_strategy_values(defn.strategies),
        )

    @run_in_thread
    def _make_match_params(
        self, candidates: Collection[TFolderHashCandidate]
    ) -> _WagoMatchRequest:
        return {
            'game_version': self._manager.config.game_flavour.to_flavour_keyed_enum(
                _WagoGameVersion
            ),
            'addons': [
                {
                    'name': c.name,
                    'hash': c.hash_contents(AddonHashMethod.wowup),
                }
                for c in candidates
            ],
        }

    async def get_folder_hash_matches(
        self, candidates: Collection[TFolderHashCandidate]
    ) -> Iterable[tuple[Defn, frozenset[TFolderHashCandidate]]]:
        async with self._manager.web_client.post(
            self._wago_external_api_url / 'addons/_match',
            expire_after=timedelta(minutes=15),
            headers=await self.make_request_headers(),
            json=await self._make_match_params(candidates),
            raise_for_status=True,
            trace_request_ctx=make_generic_progress_ctx('Finding matching Wago add-ons'),
        ) as response:
            matches: _WagoMatches = await response.json()

        candidates_by_name = {c.name: c for c in candidates}

        return [
            (
                Defn(self.metadata.id, a['id']),
                # We are filtering out add-ons without same-flavour TOCs on our end,
                # so the API might return modules which aren't in the candidate list.
                frozenset(f for m in a['modules'] for f in (candidates_by_name.get(m),) if f),
            )
            for a in matches['addons']
            if a
        ]
