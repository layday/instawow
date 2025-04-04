from __future__ import annotations

import re
from collections.abc import Collection, Sequence
from datetime import UTC, datetime, timedelta
from itertools import takewhile
from typing import Literal
from typing import NotRequired as N

from typing_extensions import TypedDict
from yarl import URL

from .. import http_ctx, sync_ctx
from .._logging import logger
from .._utils.aio import gather
from .._utils.iteration import uniq
from .._utils.text import slugify
from .._utils.web import as_plain_text_data_url
from ..definitions import ChangelogFormat, Defn, SourceMetadata
from ..progress_reporting import make_download_progress
from ..resolvers import BaseResolver, CatalogueEntryCandidate, PkgCandidate
from ..results import PkgNonexistent, resultify
from ..wow_installations import Flavour, FlavourVersionRange

_LOAD_WOWI_CATALOGUE_LOCK = (object(), '_LOAD_WOWI_CATALOGUE_LOCK_')


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


def _timestamp_to_datetime(timestamp: int):
    return datetime.fromtimestamp(timestamp / 1000, UTC)


class WowiResolver(BaseResolver):
    metadata = SourceMetadata(
        id='wowi',
        name='WoWInterface',
        strategies=frozenset(),
        changelog_format=ChangelogFormat.Raw,
        addon_toc_key='X-WoWI-ID',
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
    __list_api_url = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    __details_api_url = URL('https://api.mmoui.com/v3/game/WOW/filedetails/')

    def get_alias_from_url(self, url: URL):
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

    async def __get_addons(self):
        async with sync_ctx.locks()[_LOAD_WOWI_CATALOGUE_LOCK]:
            async with http_ctx.web_client().get(
                self.__list_api_url,
                expire_after=timedelta(hours=1),
                raise_for_status=True,
                trace_request_ctx={
                    'progress': make_download_progress(
                        label=f'Fetching {self.metadata.name} catalogue'
                    )
                },
            ) as response:
                return {i['UID']: i for i in await response.json()}

    async def __get_addons_details(self, ids: Collection[str]):
        async with http_ctx.web_client().get(
            (self.__details_api_url / f'{",".join(uniq(i for i in ids if i))}.json'),
            expire_after=timedelta(minutes=5),
            trace_request_ctx={
                'progress': make_download_progress(
                    label=f'Fetching {self.metadata.name} add-on details'
                )
            },
        ) as response:
            if response.status == 404:
                return None

            response.raise_for_status()

            return {i['UID']: i for i in await response.json()}

    async def resolve(self, defns: Sequence[Defn]):
        defns_to_ids = {d: ''.join(takewhile(str.isdigit, d.alias)) for d in defns}

        addons = await self.__get_addons()
        addons_details = await self.__get_addons_details(defns_to_ids.values())
        if addons_details is None:
            return await super().resolve(defns)

        resolve_one = resultify(self.resolve_one)
        results = await gather(
            resolve_one(
                d,
                a | b if (a := addons.get(i)) and (b := addons_details.get(i)) else None,
            )
            for d, i in defns_to_ids.items()
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: _WowiCombinedItem | None):
        if metadata is None:
            raise PkgNonexistent

        return PkgCandidate(
            id=metadata['UID'],
            slug=slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
            name=metadata['UIName'],
            description=metadata['UIDescription'],
            url=metadata['UIFileInfoURL'],
            download_url=metadata['UIDownload'],
            date_published=_timestamp_to_datetime(metadata['UIDate']),
            version=metadata['UIVersion'],
            changelog_url=as_plain_text_data_url(metadata['UIChangeLog']),
        )

    async def catalogue(self):
        logger.debug(f'Retrieving {self.__list_api_url}')

        async with http_ctx.web_client().get(
            self.__list_api_url, raise_for_status=True
        ) as response:
            items: list[_WowiListApiItem] = await response.json()

        for item in items:
            match item:
                case {'UICATID': '160'}:
                    game_flavours = (Flavour.VanillaClassic,)
                case {'UICATID': '161'}:
                    # TBC Classic
                    continue
                case {'UICATID': '162'}:
                    game_flavours = (Flavour.Classic,)
                case _:
                    compatibility = item['UICompatibility']
                    if compatibility is None or len(compatibility) < 2:
                        game_flavours = (Flavour.Retail,)
                    else:
                        game_flavours = (
                            Flavour.from_flavour_keyed_enum(r)
                            for c in compatibility
                            if (r := FlavourVersionRange.from_version(c['version']))
                        )

            yield CatalogueEntryCandidate(
                id=item['UID'],
                name=item['UIName'],
                url=item['UIFileInfoURL'],
                game_flavours=frozenset(game_flavours),
                download_count=int(item['UIDownloadTotal']),
                last_updated=_timestamp_to_datetime(item['UIDate']),
                folders=[frozenset(item['UIDir'])],
            )
