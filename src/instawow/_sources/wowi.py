from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from itertools import takewhile
from typing import Literal, NotRequired

from typing_extensions import TypedDict
from yarl import URL

from .. import http_ctx
from .._logging import logger
from .._utils.aio import gather
from .._utils.iteration import uniq
from .._utils.text import normalise_names
from .._utils.web import as_plain_text_data_url
from ..definitions import ChangelogFormat, Defn, SourceMetadata
from ..resolvers import BaseResolver, CatalogueEntryCandidate, PkgCandidate
from ..results import PkgNonexistent, resultify
from ..wow_installations import Flavour, FlavourVersions, to_flavour

_slugify = normalise_names('-')


class _WowiCommonTerms(TypedDict):
    UID: str  # Unique add-on ID
    UICATID: str  # ID of category add-on is placed in
    UIVersion: str  # Add-on version
    UIDate: int  # Upload date expressed as unix epoch
    UIName: str  # User-facing add-on name
    UIAuthorName: str


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
    UIDonationLink: NotRequired[str | None]  # Absent from the first item on the list (!)


class _WowiListApiItem_CompatibilityEntry(TypedDict):
    version: str  # Game version, e.g. '8.3.0'
    name: str  # Xpac or patch name, e.g. "Visions of N'Zoth" for 8.3.0


class _WowiDetailsApiItem(_WowiCommonTerms):
    UIMD5: str | None  # Archive hash, ``null` when review pending
    UIFileName: str  # The actual filename, e.g. 'foo.zip'
    UIDownload: str  # Download URL
    UIPending: Literal['0', '1']  # Set to '1' if the file is awaiting approval
    UIDescription: str  # Long description with BB Code and all
    UIChangeLog: str  # This can also contain BB Code
    UIHitCount: str  # Same as UIDownloadTotal
    UIHitCountMonthly: str  # Same as UIDownloadMonthly


def _timestamp_to_datetime(timestamp: int):
    return datetime.fromtimestamp(timestamp / 1000, UTC)


class WowiResolver(BaseResolver[_WowiDetailsApiItem]):
    metadata = SourceMetadata(
        id='wowi',
        name='WoWInterface',
        strategies=frozenset(),
        changelog_format=ChangelogFormat.Raw,
        addon_toc_key='X-WoWI-ID',
    )

    # Ref: https://api.mmoui.com/v3/globalconfig.json
    # There's also a v4 API corresponding to the unreleased Minion v4,
    # which is fair to assume is unstable.  The naming scheme was changed to
    # camel case and some fields which contained strings were turned into numbers.
    # Neither API provides access to classic files for multi-file add-ons and
    # ``UICompatibility`` can't be relied on to enforce compatibility - not only
    # because it's not consistently populated, but also because it's not
    # reported by the details endpoint and keeping the two endpoints
    # in sync is tricky.
    # We could theoretically inspect the downloaded file for compatbility,
    # but that's a lot of bandwidth to be wasting on add-ons which might
    # not end up being installed.
    # The API appears to inherit the version of the latest
    # file to have been uploaded, which for multi-file add-ons can be the
    # classic version.  Hoooowever, the download link always points to the
    # 'retail' version.
    # In essence, the WoWI API is only good for installing retail add-ons.
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

    async def resolve(self, defns: Sequence[Defn]):
        defn_ids = {d: ''.join(takewhile(str.isdigit, d.alias)) for d in defns}

        async with http_ctx.web_client().get(
            (self.__details_api_url / f'{",".join(uniq(filter(None, defn_ids.values())))}.json'),
            expire_after=timedelta(minutes=15),
        ) as response:
            if response.status == 404:
                return await super().resolve(defns)

            response.raise_for_status()

            addons_details = {i['UID']: i for i in await response.json()}

        resolve_one = resultify(self.resolve_one)
        results = await gather(resolve_one(d, addons_details.get(i)) for d, i in defn_ids.items())
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: _WowiDetailsApiItem | None):
        if metadata is None:
            raise PkgNonexistent

        return PkgCandidate(
            id=metadata['UID'],
            slug=_slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
            name=metadata['UIName'],
            description=metadata['UIDescription'],
            url=f'https://www.wowinterface.com/downloads/info{metadata["UID"]}',
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

        supported_flavours = frozenset(Flavour)

        for item in items:
            match item:
                case {'UICompatibility': list(compatibility)}:
                    yield CatalogueEntryCandidate(
                        id=item['UID'],
                        name=item['UIName'],
                        url=item['UIFileInfoURL'],
                        game_flavours=supported_flavours.intersection(
                            to_flavour(f)
                            for c in compatibility
                            for f in (FlavourVersions.from_version_string(c['version']),)
                            if f
                        ),
                        download_count=int(item['UIDownloadTotal']),
                        last_updated=_timestamp_to_datetime(item['UIDate']),
                        folders=[frozenset(item['UIDir'])],
                    )

                case _:
                    continue
