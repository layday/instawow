from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone

from loguru import logger
from typing_extensions import Literal, TypedDict
from yarl import URL

from .. import _deferred_types, manager, models, results as R
from ..cataloguer import BaseCatalogueEntry
from ..common import ChangelogFormat, Flavour, SourceMetadata, Strategy
from ..resolvers import BaseResolver, Defn, format_data_changelog, slugify
from ..utils import StrEnum, gather


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
    patch: str
    screenshot_url: str
    small_desc: str
    ticket: str
    url: str
    version: str
    web_url: str


class _TukuiAddon(TypedDict):
    author: str
    category: str
    changelog: str
    donate_url: str
    downloads: str  # Not a mistake, it is actually a string
    id: str
    last_download: str
    # ISO *datetime* with space sep and without an offset, e.g. '2020-02-02 12:12:20'
    lastupdate: str
    name: str
    patch: str | None
    screenshot_url: str
    small_desc: str
    url: str
    version: str
    web_url: str


class _TukuiFlavourQueryParam(StrEnum):
    _ignore_ = ['wrath_classic']

    retail = 'addons'
    vanilla_classic = 'classic-addons'
    burning_crusade_classic = 'classic-tbc-addons'
    wrath_classic = ...


class TukuiResolver(BaseResolver):
    metadata = SourceMetadata(
        id='tukui',
        name='Tukui',
        strategies=frozenset({Strategy.default}),
        changelog_format=ChangelogFormat.html,
    )

    # There's also a ``/client-api.php`` endpoint which is apparently
    # used by the Tukui client itself to check for updates for the two retail
    # UIs only.  The response body appears to be identical to ``/api.php``
    _api_url = URL('https://www.tukui.org/api.php')

    _RETAIL_UI_SUITES = frozenset(('elvui', 'tukui'))

    _FLAVOUR_URL_PATHS = frozenset(f'/{p}.php' for p in _TukuiFlavourQueryParam)

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if url.host == 'www.tukui.org':
            if url.path in cls._FLAVOUR_URL_PATHS:
                return url.query.get('id')
            elif url.path == '/download.php':
                return url.query.get('ui')

    async def _synchronise(self) -> dict[str, _TukuiAddon | _TukuiUi]:
        async def fetch_ui(ui_slug: str):
            async with self._manager.web_client.get(
                self._api_url.with_query({'ui': ui_slug}),
                {'minutes': 5},
                raise_for_status=True,
            ) as response:
                addon: _TukuiUi = await response.json()
                return [(str(addon['id']), addon), (ui_slug, addon)]

        async def fetch_addons(flavour: Flavour):
            addons: list[tuple[str, _TukuiAddon]] = []

            try:
                param = self._manager.config.game_flavour.to_flavour_keyed_enum(
                    _TukuiFlavourQueryParam
                )
            except KeyError:
                pass
            else:
                async with self._manager.web_client.get(
                    self._api_url.with_query({param.value: 'all'}),
                    {'minutes': 30},
                    label=f'Synchronising {self.metadata.name} {flavour} catalogue',
                    raise_for_status=True,
                ) as response:
                    addons = [(str(a['id']), a) for a in await response.json()]

            return addons

        async with self._manager.locks['load Tukui catalogue']:
            return {
                k: v
                for l in await gather(
                    (
                        *(
                            fetch_ui(s)
                            for s in (
                                self._RETAIL_UI_SUITES
                                if self._manager.config.game_flavour is Flavour.retail
                                else ()
                            )
                        ),
                        fetch_addons(self._manager.config.game_flavour),
                    )
                )
                for k, v in l
            }

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        addons = await self._synchronise()
        ids = (
            d.alias[:p] if d.alias not in self._RETAIL_UI_SUITES and p != -1 else d.alias
            for d in defns
            for p in (d.alias.find('-', 1),)
        )
        results = await gather(
            (self.resolve_one(d, addons.get(i)) for d, i in zip(defns, ids)),
            manager.capture_manager_exc_async,
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: _TukuiAddon | _TukuiUi | None) -> models.Pkg:
        if metadata is None:
            raise R.PkgNonexistent

        if metadata['id'] == -1:
            slug = 'tukui'
        elif metadata['id'] == -2:
            slug = 'elvui'
        else:
            slug = slugify(f'{metadata["id"]} {metadata["name"]}')

        return models.Pkg(
            source=self.metadata.id,
            id=str(metadata['id']),
            slug=slug,
            name=metadata['name'],
            description=metadata['small_desc'],
            url=metadata['web_url'],
            download_url=metadata['url'],
            date_published=datetime.fromisoformat(metadata['lastupdate']).replace(
                tzinfo=timezone.utc
            ),
            version=metadata['version'],
            changelog_url=(
                # The changelog URL is not versioned - adding fragment to allow caching
                str(URL(metadata['changelog']).with_fragment(metadata['version']))
                if metadata['id'] in {-1, -2}
                # Regular add-ons don't have dedicated changelogs
                # but link to the changelog tab on the add-on page
                else format_data_changelog(metadata['changelog'])
            ),
            options=models.PkgOptions(strategy=defn.strategy),
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        for flavours, query in [
            (frozenset({Flavour.retail}), {'ui': 'tukui'}),
            (frozenset({Flavour.retail}), {'ui': 'elvui'}),
            *(
                (frozenset({Flavour.from_flavour_keyed_enum(p)}), {p.value: 'all'})
                for p in _TukuiFlavourQueryParam
            ),
        ]:
            url = cls._api_url.with_query(query)
            logger.debug(f'retrieving {url}')
            async with web_client.get(url, raise_for_status=True) as response:
                items: _TukuiUi | list[_TukuiAddon] = await response.json(
                    content_type=None  # text/html
                )

            for item in items if isinstance(items, list) else [items]:
                yield BaseCatalogueEntry(
                    source=cls.metadata.id,
                    id=str(item['id']),
                    name=item['name'],
                    url=item['web_url'],
                    game_flavours=flavours,
                    # Split Tukui and ElvUI downloads evenly between them.
                    # They both have the exact same number of downloads so
                    # I'm assuming they're being counted together.
                    # This should help with scoring other add-ons on the
                    # Tukui catalogue higher
                    download_count=int(item['downloads']) // (2 if item['id'] in {-1, -2} else 1),
                    last_updated=datetime.fromisoformat(item['lastupdate']).replace(
                        tzinfo=timezone.utc
                    ),
                )
