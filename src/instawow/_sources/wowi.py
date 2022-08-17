from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from itertools import takewhile
import re

from loguru import logger
from typing_extensions import Literal, NotRequired as N, TypedDict
from yarl import URL

from .. import _deferred_types, manager, models, results as R
from ..cataloguer import BaseCatalogueEntry
from ..common import ChangelogFormat, Flavour, FlavourVersion, SourceMetadata, Strategy
from ..resolvers import BaseResolver, Defn, format_data_changelog, slugify
from ..utils import gather


class _WowiCommonTerms(TypedDict):
    UID: str  # Unique add-on ID
    UICATID: str  # ID of category add-on is placed in
    UIVersion: str  # Add-on version
    UIDate: int  # Upload date expressed as unix epoch
    UIName: str  # User-facing add-on name
    UIAuthorName: str


class _WowiListApiItem_CompatibilityEntry(TypedDict):
    version: str  # Game version, e.g. '8.3.0'
    name: str  # Xpac or patch name, e.g. "Visions of N'Zoth" for 8.3.0


class _WowiListApiItem(_WowiCommonTerms):
    UIFileInfoURL: str  # Add-on page on WoWI
    UIDownloadTotal: str  # Total number of downloads
    UIDownloadMonthly: str  # Number of downloads in the last month and not 'monthly'
    UIFavoriteTotal: str
    UICompatibility: list[_WowiListApiItem_CompatibilityEntry] | None  # ``null`` if would be empty
    UIDir: list[str]  # Names of folders contained in archive
    UIIMG_Thumbs: list[str] | None  # Thumbnail URLs; ``null`` if would be empty
    UIIMGs: list[str] | None  # Full-size image URLs; ``null`` if would be empty
    # There are only two add-ons on the entire list with siblings
    # (they refer to each other). I don't know if this was meant to capture
    # dependencies (probably not) but it's so underused as to be worthless.
    # ``null`` if would be empty
    UISiblings: list[str] | None
    UIDonationLink: N[str | None]  # Absent from the first item on the list (!)


class _WowiDetailsApiItem(_WowiCommonTerms):
    UIMD5: str | None  # Archive hash, ``null` when review pending
    UIFileName: str  # The actual filename, e.g. 'foo.zip'
    UIDownload: str  # Download URL
    UIPending: Literal['0', '1']  # Set to '1' if the file is awaiting approval
    UIDescription: str  # Long description with BB Code and all
    UIChangeLog: str  # This can also contain BB Code
    UIHitCount: str  # Same as UIDownloadTotal
    UIHitCountMonthly: str  # Same as UIDownloadMonthly


class _WowiCombinedItem(_WowiListApiItem, _WowiDetailsApiItem):
    pass


class WowiResolver(BaseResolver):
    metadata = SourceMetadata(
        id='wowi',
        name='WoWInterface',
        strategies=frozenset({Strategy.default}),
        changelog_format=ChangelogFormat.raw,
    )

    # Reference: https://api.mmoui.com/v3/globalconfig.json
    # There's also a v4 API corresponding to the as yet unreleased Minion v4,
    # which is fair to assume is unstable.  They changed the naming scheme to
    # camelCase and some fields which were strings were converted to numbers.
    # Neither API provides access to classic files for multi-file add-ons and
    # 'UICompatibility' can't be relied on to enforce compatibility
    # in instawow.  The API appears to inherit the version of the latest
    # file to have been uploaded, which for multi-file add-ons can be the
    # classic version.  Hoooowever the download link always points to the
    # 'retail' version, which for single-file add-ons belonging to the
    # classic category would be an add-on for classic.
    _list_api_url = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    _details_api_url = URL('https://api.mmoui.com/v3/game/WOW/filedetails/')

    @classmethod
    def _timestamp_to_datetime(cls, timestamp: int):
        return datetime.fromtimestamp(timestamp / 1000, timezone.utc)

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if (
            url.host in {'wowinterface.com', 'www.wowinterface.com'}
            and len(url.parts) == 3
            and url.parts[1] == 'downloads'
        ):
            if url.name == 'landing.php':
                return url.query.get('fileid')
            elif url.name == 'fileinfo.php':
                return url.query.get('id')
            else:
                match = re.match(r'^(?:download|info)(?P<id>\d+)', url.name)
                return match and match['id']

    async def _synchronise(self):
        async with self._manager.locks['load WoWI catalogue']:
            async with self._manager.web_client.get(
                self._list_api_url,
                {'hours': 1},
                label=f'Synchronising {self.metadata.name} catalogue',
                raise_for_status=True,
            ) as response:
                list_api_items: list[_WowiListApiItem] = await response.json()
                return {i['UID']: i for i in list_api_items}

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        list_api_items = await self._synchronise()

        defns_to_ids = {d: ''.join(takewhile(str.isdigit, d.alias)) for d in defns}
        numeric_ids = frozenset(filter(None, defns_to_ids.values()))
        async with self._manager.web_client.get(
            self._details_api_url / f'{",".join(numeric_ids)}.json',
            {'minutes': 5},
        ) as response:
            if response.status == 404:
                return await super().resolve(defns)
            else:
                response.raise_for_status()
                details_api_items: list[_WowiDetailsApiItem] = await response.json()

        combined_items: dict[str, _WowiCombinedItem] = {
            i['UID']: {**list_api_items[i['UID']], **i} for i in details_api_items
        }
        results = await gather(
            (self.resolve_one(d, combined_items.get(i)) for d, i in defns_to_ids.items()),
            manager.capture_manager_exc_async,
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: _WowiCombinedItem | None) -> models.Pkg:
        if metadata is None:
            raise R.PkgNonexistent

        return models.Pkg(
            source=self.metadata.id,
            id=metadata['UID'],
            slug=slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
            name=metadata['UIName'],
            description=metadata['UIDescription'],
            url=metadata['UIFileInfoURL'],
            download_url=metadata['UIDownload'],
            date_published=self._timestamp_to_datetime(metadata['UIDate']),
            version=metadata['UIVersion'],
            changelog_url=format_data_changelog(metadata['UIChangeLog']),
            options=models.PkgOptions(strategy=defn.strategy),
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        logger.debug(f'retrieving {cls._list_api_url}')

        async with web_client.get(cls._list_api_url, raise_for_status=True) as response:
            items: list[_WowiListApiItem] = await response.json()

        for item in items:
            if item['UICATID'] == '160':
                game_flavours = {Flavour.vanilla_classic}
            elif item['UICATID'] == '161':
                game_flavours = {Flavour.burning_crusade_classic}
            elif item['UICATID'] == '162':
                game_flavours = {Flavour.wrath_classic}
            elif item['UICompatibility'] is None or len(item['UICompatibility']) < 2:
                game_flavours = {Flavour.retail}
            else:
                game_flavours = {
                    Flavour.from_flavour_keyed_enum(f)
                    for c in item['UICompatibility']
                    for f in (FlavourVersion.from_version_string(c['version']),)
                    if f
                }

            yield BaseCatalogueEntry(
                source=cls.metadata.id,
                id=item['UID'],
                name=item['UIName'],
                url=item['UIFileInfoURL'],
                game_flavours=frozenset(game_flavours),
                download_count=int(item['UIDownloadTotal']),
                last_updated=cls._timestamp_to_datetime(item['UIDate']),
                folders=[frozenset(item['UIDir'])],
            )
