from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timezone
from enum import IntEnum
from itertools import chain, count, takewhile, tee, zip_longest
from pathlib import Path
import re
import typing
from typing import Any, ClassVar
import urllib.parse

from attrs import evolve, frozen
import iso8601
from loguru import logger
from typing_extensions import Literal, NotRequired as N, Protocol, Self, TypedDict
from yarl import URL

from . import _deferred_types, manager, models, results as R
from .cataloguer import BaseCatalogueEntry, CatalogueSameAs
from .common import ChangelogFormat, Flavour, FlavourVersion, SourceMetadata, Strategy
from .config import GlobalConfig
from .utils import (
    StrEnum,
    TocReader,
    extract_byte_range_offset,
    file_uri_to_path,
    find_addon_zip_tocs,
    gather,
    normalise_names,
    run_in_thread,
    uniq,
)


@frozen(hash=True)
class Defn:
    source: str
    alias: str
    id: typing.Optional[str] = None
    strategy: Strategy = Strategy.default
    version: typing.Optional[str] = None

    @classmethod
    def from_pkg(cls, pkg: models.Pkg) -> Defn:
        return cls(pkg.source, pkg.slug, pkg.id, pkg.options.strategy, pkg.version)

    def with_version(self, version: str) -> Defn:
        return evolve(self, strategy=Strategy.version, version=version)

    def to_urn(self) -> str:
        return f'{self.source}:{self.alias}'


_slugify = normalise_names('-')


def _format_data_changelog(changelog: str = '') -> str:
    return f'data:,{urllib.parse.quote(changelog)}'


class Resolver(Protocol):
    metadata: ClassVar[SourceMetadata]

    def __init__(self, manager: manager.Manager) -> None:
        ...

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        "Attempt to extract a ``Defn`` alias from a given URL."
        ...

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        "Resolve multiple ``Defn``s into packages."
        ...

    async def resolve_one(self, defn: Defn, metadata: Any) -> models.Pkg:
        "Resolve a ``Defn`` into a package."
        ...

    async def get_changelog(self, uri: URL) -> str:
        "Retrieve a changelog from a URI."
        ...

    @classmethod
    def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        "Enumerate add-ons from the source."
        ...


class BaseResolver(Resolver):
    metadata: ClassVar[SourceMetadata]

    def __init__(self, manager: manager.Manager) -> None:
        self._manager = manager

    def __init_subclass__(cls) -> None:
        async def resolve_one(self: Self, defn: Defn, metadata: Any) -> models.Pkg:
            if defn.strategy not in self.metadata.strategies:
                raise R.PkgStrategyUnsupported(defn.strategy)
            return await orig_resolve_one(self, defn, metadata)

        kls = cls
        orig_resolve_one = kls.resolve_one
        kls.resolve_one = resolve_one

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        return None

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        results = await gather(
            (self.resolve_one(d, None) for d in defns), manager.capture_manager_exc_async
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: Any) -> models.Pkg:
        raise NotImplementedError

    async def get_changelog(self, uri: URL) -> str:
        if uri.scheme == 'data' and uri.raw_path.startswith(','):
            return urllib.parse.unquote(uri.raw_path[1:])
        elif uri.scheme in {'http', 'https'}:
            async with self._manager.web_client.get(
                uri, {'days': 1}, raise_for_status=True
            ) as response:
                return await response.text()
        elif uri.scheme == 'file':
            return await run_in_thread(Path(file_uri_to_path(str(uri))).read_text)(
                encoding='utf-8'
            )
        else:
            raise ValueError('Unsupported URI with scheme', uri.scheme)

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        return
        yield


class _CfCoreModLinks(TypedDict):
    websiteUrl: str
    wikiUrl: str
    issuesUrl: str
    sourceUrl: str


class _CfCoreModStatus(IntEnum):
    new = 1
    changed_required = 2
    under_soft_review = 3
    approved = 4
    rejected = 5
    changes_made = 6
    inactive = 7
    abandoned = 8
    deleted = 9
    under_review = 10


class _CfCoreCategory(TypedDict):
    id: int
    gameId: int
    name: str
    slug: str
    url: str
    iconUrl: str
    dateModified: str  # date-time
    isClass: bool
    classId: int
    parentCategoryId: int


class _CfCoreModAuthor(TypedDict):
    id: int
    name: str
    url: str


class _CfCoreModAsset(TypedDict):
    id: int
    modId: int
    title: str
    description: str
    thumbnailUrl: str
    url: str


class _CfCoreFileIndex(TypedDict):
    gameVersion: str
    fileId: int
    filename: str
    releaseType: _CfCoreFileReleaseType
    gameVersionTypeId: int
    modLoader: int


class _CfCoreFileStatus(IntEnum):
    processing = 1
    changes_required = 2
    under_review = 3
    approved = 4
    rejected = 5
    malware_detected = 6
    deleted = 7
    archived = 8
    testing = 9
    released = 10
    ready_for_review = 11
    deprecated = 12
    baking = 13
    awaiting_publishing = 14
    failed_publishing = 15


class _CfCoreFileReleaseType(IntEnum):
    release = 1
    beta = 2
    alpha = 3


class _CfCoreHashAlgo(IntEnum):
    sha1 = 1
    md5 = 2


class _CfCoreFileHash(TypedDict):
    value: str
    algo: _CfCoreHashAlgo


class _CfCoreSortableGameVersionTypeId(IntEnum):
    retail = 517
    vanilla_classic = 67408
    burning_crusade_classic = 73246


class _CfCoreSortableGameVersion(TypedDict):
    gameVersionName: str
    gameVersionPadded: str
    gameVersion: str
    gameVersionReleaseDate: str  # date-time
    gameVersionTypeId: _CfCoreSortableGameVersionTypeId


class _CfCoreFileRelationType(IntEnum):
    embedded_library = 1
    optional_dependency = 2
    required_dependency = 3
    tool = 4
    incompatible = 5
    include = 6


class _CfCoreFileDependency(TypedDict):
    modId: int
    fileId: int
    relationType: _CfCoreFileRelationType


class _CfCoreFileModule(TypedDict):
    name: str
    fingerprint: int


class _CfCoreFile(TypedDict):
    id: int
    gameId: int
    modId: int
    isAvailable: bool
    displayName: str
    fileName: str
    releaseType: _CfCoreFileReleaseType
    fileStatus: _CfCoreFileStatus
    hashes: list[_CfCoreFileHash]
    fileDate: str  # date-time
    fileLength: int
    downloadCount: int
    downloadUrl: str
    gameVersions: list[str]
    sortableGameVersions: list[_CfCoreSortableGameVersion]
    dependencies: list[_CfCoreFileDependency]
    exposeAsAlternative: N[bool]
    parentProjectFileId: N[int]
    alternateFileId: int
    isServerPack: bool
    serverPackFileId: N[int]
    fileFingerprint: int
    modules: list[_CfCoreFileModule]


class _CfCoreMod(TypedDict):
    id: int
    gameId: int
    name: str
    slug: str
    links: _CfCoreModLinks
    summary: str
    status: _CfCoreModStatus
    downloadCount: int
    isFeatured: bool
    primaryCategoryId: int
    categories: list[_CfCoreCategory]
    authors: list[_CfCoreModAuthor]
    logo: _CfCoreModAsset
    screenshots: list[_CfCoreModAsset]
    mainFileId: int
    latestFiles: list[_CfCoreFile]
    latestFilesIndexes: list[_CfCoreFileIndex]
    dateCreated: str  # date-time
    dateModified: str  # date-time
    dateReleased: str  # date-time
    allowModDistribution: bool | None


class _CfCoreModsSearchSortField(IntEnum):
    featured = 1
    popularity = 2
    last_updated = 3
    name_ = 4
    author = 5
    total_downloads = 6
    category = 7
    game_version = 8


class _CfCoreStringDataResponse(TypedDict):
    data: str


class _CfCoreModsResponsePagination(TypedDict):
    index: int
    pageSize: int
    resultCount: int
    totalCount: int | None


class _CfCoreModsResponseSansPagination(TypedDict):
    data: list[_CfCoreMod]


class _CfCoreModsResponse(TypedDict):
    data: list[_CfCoreMod]
    pagination: _CfCoreModsResponsePagination


class _CfCoreFilesResponse(TypedDict):
    data: list[_CfCoreFile]
    pagination: _CfCoreModsResponsePagination


class CfCoreResolver(BaseResolver):
    metadata = SourceMetadata(
        id='curse',
        name='CFCore',
        strategies=frozenset(
            {
                Strategy.default,
                Strategy.latest,
                Strategy.any_flavour,
                Strategy.version,
            }
        ),
        changelog_format=ChangelogFormat.html,
    )

    # Ref: https://docs.curseforge.com/
    _mod_api_url = URL('https://api.curseforge.com/v1/mods')

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if (
            url.host == 'www.curseforge.com'
            and len(url.parts) > 3
            and url.parts[1:3] == ('wow', 'addons')
        ):
            return url.parts[3].lower()

    @classmethod
    def _get_access_token(cls, global_config: GlobalConfig):
        maybe_access_token = global_config.access_tokens.cfcore
        if maybe_access_token is None:
            raise ValueError('CFCore access token not configured')
        return maybe_access_token

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        catalogue = await self._manager.synchronise()

        defns_to_maybe_numeric_ids = {
            d: i if i.isdigit() else None
            for d in defns
            for i in (d.id or catalogue.curse_slugs.get(d.alias) or d.alias,)
        }
        numeric_ids = uniq(i for i in defns_to_maybe_numeric_ids.values() if i is not None)
        if not numeric_ids:
            return await super().resolve(defns)

        async with self._manager.web_client.request(
            'POST',
            self._mod_api_url,
            {'minutes': 5},
            headers={'x-api-key': self._get_access_token(self._manager.config.global_config)},
            json={'modIds': numeric_ids},
        ) as response:
            if response.status == 404:
                return await super().resolve(defns)

            response.raise_for_status()
            response_json: _CfCoreModsResponseSansPagination = await response.json()

        numeric_ids_to_addons: dict[str | None, _CfCoreMod] = {
            str(r['id']): r for r in response_json['data']
        }
        results = await gather(
            (
                self.resolve_one(d, numeric_ids_to_addons.get(i))
                for d, i in defns_to_maybe_numeric_ids.items()
            ),
            manager.capture_manager_exc_async,
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: _CfCoreMod | None) -> models.Pkg:
        if metadata is None:
            raise R.PkgNonexistent

        if defn.strategy is Strategy.version:
            async with self._manager.web_client.get(
                (self._mod_api_url / str(metadata['id']) / 'files').with_query(
                    gameVersionTypeId=self._manager.config.game_flavour.to_flavour_keyed_enum(
                        _CfCoreSortableGameVersionTypeId
                    ),
                    pageSize=9999,
                ),
                {'hours': 1},
                headers={'x-api-key': self._get_access_token(self._manager.config.global_config)},
                label=f'Fetching metadata from {self.metadata.name}',
                raise_for_status=True,
            ) as response:
                response_json: _CfCoreFilesResponse = await response.json()

            file = next(
                (f for f in response_json['data'] if defn.version == f['displayName']), None
            )
            if file is None:
                raise R.PkgFileUnavailable(f'version {defn.version} not found')

        else:
            latest_files = metadata['latestFiles']
            if not latest_files:
                raise R.PkgFileUnavailable('no files available for download')

            def make_filter():
                def is_not_libless(f: _CfCoreFile):
                    return not f.get('exposeAsAlternative', False)

                yield is_not_libless

                if defn.strategy is not Strategy.any_flavour:

                    type_id = self._manager.config.game_flavour.to_flavour_keyed_enum(
                        _CfCoreSortableGameVersionTypeId
                    )

                    def supports_flavour(f: _CfCoreFile):
                        return any(
                            s['gameVersionTypeId'] == type_id for s in f['sortableGameVersions']
                        )

                    yield supports_flavour

                if defn.strategy is not Strategy.latest:

                    def is_stable_release(f: _CfCoreFile):
                        return f['releaseType'] == _CfCoreFileReleaseType.release

                    yield is_stable_release

            filter_fns = list(make_filter())

            file = max(
                (f for f in latest_files if all(l(f) for l in filter_fns)),
                # The ``id`` is just a counter so we don't have to go digging around dates
                key=lambda f: f['id'],
                default=None,
            )
            if file is None:
                raise R.PkgFileUnavailable(
                    f'no files matching {self._manager.config.game_flavour} '
                    f'using {defn.strategy} strategy'
                )

        return models.Pkg(
            source=self.metadata.id,
            id=str(metadata['id']),
            slug=metadata['slug'],
            name=metadata['name'],
            description=metadata['summary'],
            url=metadata['links']['websiteUrl'],
            download_url=file['downloadUrl'],
            date_published=iso8601.parse_date(file['fileDate']),
            version=file['displayName'],
            changelog_url=str(
                self._mod_api_url / f'{metadata["id"]}/files/{file["id"]}/changelog'
            ),
            options=models.PkgOptions(strategy=defn.strategy),
            deps=[
                models.PkgDep(id=str(d['modId']))
                for d in file['dependencies']
                if d['relationType'] == _CfCoreFileRelationType.required_dependency
            ],
        )

    async def get_changelog(self, uri: URL) -> str:
        headers = {'x-api-key': self._get_access_token(self._manager.config.global_config)}
        async with self._manager.web_client.get(
            uri, {'days': 1}, headers=headers, raise_for_status=True
        ) as response:
            response_json: _CfCoreStringDataResponse = await response.json()
            return response_json['data']

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        from aiohttp import ClientTimeout

        from .config import GlobalConfig

        def excise_flavours(files: list[_CfCoreFile]):
            for flavour in Flavour:
                if any(
                    not f.get('exposeAsAlternative', False)
                    and any(
                        s['gameVersionTypeId']
                        == flavour.to_flavour_keyed_enum(_CfCoreSortableGameVersionTypeId)
                        for s in f['sortableGameVersions']
                    )
                    for f in files
                ):
                    yield flavour

        def excise_folders(files: list[_CfCoreFile]):
            return uniq(frozenset(m['name'] for m in f['modules']) for f in files)

        timeout = ClientTimeout(total=10)
        headers = {'x-api-key': cls._get_access_token(GlobalConfig.from_env())}
        step = 50

        for index in count():
            url = (cls._mod_api_url / 'search').with_query(
                gameId='1',
                sortField=_CfCoreModsSearchSortField.name_,
                pageSize=step,
                index=index * step,
            )
            logger.debug(f'retrieving {url}')

            for attempt in count(1):
                try:
                    async with web_client.get(
                        url, headers=headers, raise_for_status=True, timeout=timeout
                    ) as response:
                        response_json: _CfCoreModsResponse = await response.json()
                        break
                except asyncio.TimeoutError:
                    logger.debug(f'request timed out; attempt {attempt} of 3')
                    if attempt < 3:
                        continue
            else:
                raise RuntimeError('maximum number of attempts exceeded')

            items = response_json['data']
            if not items:
                break

            for item in items:
                yield BaseCatalogueEntry(
                    source=cls.metadata.id,
                    id=str(item['id']),
                    slug=item['slug'],
                    name=item['name'],
                    url=item['links']['websiteUrl'],
                    game_flavours=frozenset(excise_flavours(item['latestFiles'])),
                    download_count=item['downloadCount'],
                    last_updated=iso8601.parse_date(item['dateReleased']),
                    folders=excise_folders(item['latestFiles']),
                )


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
                details_api_items = await response.json()

        combined_items: dict[str, Any] = {
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
            slug=_slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
            name=metadata['UIName'],
            description=metadata['UIDescription'],
            url=metadata['UIFileInfoURL'],
            download_url=metadata['UIDownload'],
            date_published=self._timestamp_to_datetime(metadata['UIDate']),
            version=metadata['UIVersion'],
            changelog_url=_format_data_changelog(metadata['UIChangeLog']),
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
    api_url = URL('https://www.tukui.org/api.php')

    _retail_ui_suites = {'elvui', 'tukui'}

    _query_flavours = {
        Flavour.retail: 'addons',
        Flavour.vanilla_classic: 'classic-addons',
        Flavour.burning_crusade_classic: 'classic-tbc-addons',
    }

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if url.host == 'www.tukui.org':
            if url.path in {'/addons.php', '/classic-addons.php', '/classic-tbc-addons.php'}:
                return url.query.get('id')
            elif url.path == '/download.php':
                return url.query.get('ui')

    async def _synchronise(self) -> dict[str, _TukuiAddon | _TukuiUi]:
        async def fetch_ui(ui_slug: str):
            async with self._manager.web_client.get(
                self.api_url.with_query({'ui': ui_slug}),
                {'minutes': 5},
                raise_for_status=True,
            ) as response:
                addon: _TukuiUi = await response.json()
                return [(str(addon['id']), addon), (ui_slug, addon)]

        async def fetch_addons(flavour: Flavour):
            async with self._manager.web_client.get(
                self.api_url.with_query({self._query_flavours[flavour]: 'all'}),
                {'minutes': 30},
                label=f'Synchronising {self.metadata.name} {flavour} catalogue',
                raise_for_status=True,
            ) as response:
                addons: list[_TukuiAddon] = await response.json()
                return [(str(a['id']), a) for a in addons]

        async with self._manager.locks['load Tukui catalogue']:
            return {
                k: v
                for l in await gather(
                    chain(
                        (
                            (fetch_ui(s) for s in self._retail_ui_suites)
                            if self._manager.config.game_flavour is Flavour.retail
                            else ()
                        ),
                        (fetch_addons(self._manager.config.game_flavour),),
                    )
                )
                for k, v in l
            }

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        addons = await self._synchronise()
        ids = (
            d.alias[:p] if d.alias not in self._retail_ui_suites and p != -1 else d.alias
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
            slug = _slugify(f'{metadata["id"]} {metadata["name"]}')

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
                # Regular add-ons don't have dedicated changelogs but rather
                # link to the changelog tab on the add-on page
                else _format_data_changelog(metadata['changelog'])
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
            *((frozenset({f}), {q: 'all'}) for f, q in cls._query_flavours.items()),
        ]:
            url = cls.api_url.with_query(query)
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


# Not exhaustive (as you might've guessed).  Reference:
# https://docs.github.com/en/rest/reference/repos
class _GithubRepo(TypedDict):
    name: str  # the repo in user-or-org/repo
    full_name: str  # user-or-org/repo
    description: str | None
    html_url: str


class _GithubRelease(TypedDict):
    tag_name: str  # Hopefully the version
    published_at: str  # ISO datetime
    assets: list[_GithubRelease_Asset]
    body: str


class _GithubRelease_Asset(TypedDict):
    name: str  # filename
    content_type: str  # mime type
    state: Literal['starter', 'uploaded']
    browser_download_url: str


class _PackagerReleaseJson(TypedDict):
    releases: list[_PackagerReleaseJson_Release]


class _PackagerReleaseJson_Release(TypedDict):
    filename: str
    nolib: bool
    metadata: list[_PackagerReleaseJson_Release_Metadata]


class _PackagerReleaseJson_Release_Metadata(TypedDict):
    flavor: _PackagerReleaseJsonFlavor
    interface: int


class _PackagerReleaseJsonFlavor(StrEnum):
    retail = 'mainline'
    vanilla_classic = 'classic'
    burning_crusade_classic = 'bcc'


class GithubResolver(BaseResolver):
    metadata = SourceMetadata(
        id='github',
        name='GitHub',
        strategies=frozenset({Strategy.default, Strategy.latest, Strategy.version}),
        changelog_format=ChangelogFormat.markdown,
    )

    _repos_api_url = URL('https://api.github.com/repos')

    _generated_catalogue_csv_url = (
        'https://raw.githubusercontent.com/layday/github-wow-addon-catalogue/main/addons.csv'
    )

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if url.host == 'github.com' and len(url.parts) > 2:
            return '/'.join(url.parts[1:3])

    async def resolve_one(self, defn: Defn, metadata: None) -> models.Pkg:
        github_token = self._manager.config.global_config.access_tokens.github
        github_headers = {'Authorization': f'token {github_token}'} if github_token else {}

        repo_url = self._repos_api_url / defn.alias
        async with self._manager.web_client.get(
            repo_url, {'hours': 1}, headers=github_headers
        ) as response:
            if response.status == 404:
                raise R.PkgNonexistent
            response.raise_for_status()
            project_metadata: _GithubRepo = await response.json()

        if defn.strategy is Strategy.version:
            assert defn.version
            release_url = repo_url / 'releases/tags' / defn.version
        elif defn.strategy is Strategy.latest:
            # Includes pre-releases
            release_url = (repo_url / 'releases').with_query(per_page='1')
        else:
            # The latest release is the most recent release which is neither
            # a pre-release nor a draft
            release_url = repo_url / 'releases/latest'

        async with self._manager.web_client.get(
            release_url, {'minutes': 5}, headers=github_headers
        ) as response:
            if response.status == 404:
                raise R.PkgFileUnavailable('release not found')
            response.raise_for_status()

            response_json = await response.json()
            if defn.strategy is Strategy.latest:
                (response_json,) = response_json
            release_metadata: _GithubRelease = response_json

        assets = release_metadata['assets']

        release_json = next(
            (a for a in assets if a['name'] == 'release.json' and a['state'] == 'uploaded'),
            None,
        )
        if release_json is None:
            candidates = [
                a
                for a in assets
                if a['state'] == 'uploaded'
                and a['content_type'] in {'application/zip', 'application/x-zip-compressed'}
                and a['name'].endswith('.zip')
                # TODO: Is there a better way to detect nolib?
                and '-nolib' not in a['name']
            ]
            if not candidates:
                raise R.PkgFileUnavailable(
                    'no `release.json` attached to release, no add-on zips found'
                )

            from io import BytesIO
            import zipfile

            from aiohttp import hdrs

            from .matchers import NORMALISED_FLAVOUR_TOC_SUFFIXES

            matching_asset = None

            for candidate in candidates:
                addon_zip_stream = BytesIO()
                dynamic_addon_zip = None
                is_zip_complete = False

                for directory_offset in range(-25_000, -100_001, -25_000):
                    logger.debug(
                        f'fetching {abs(directory_offset):,d} bytes from end of {candidate["name"]}'
                    )

                    # TODO: Take min of (directory_offset, remaining size from prev request)
                    #       to avoid 416 error if a small zip has an inordinately large directory.

                    async with self._manager.web_client.wrapped.get(
                        candidate['browser_download_url'],
                        headers={**github_headers, hdrs.RANGE: f'bytes={directory_offset}'},
                    ) as directory_range_response:
                        if not directory_range_response.ok:
                            # File size under 25 KB.
                            if directory_range_response.status == 416:  # Range Not Satisfiable
                                async with self._manager.web_client.get(
                                    candidate['browser_download_url'],
                                    {'days': 30},
                                    headers=github_headers,
                                    raise_for_status=True,
                                ) as addon_zip_response:
                                    addon_zip_stream.write(await addon_zip_response.read())

                                is_zip_complete = True
                                dynamic_addon_zip = zipfile.ZipFile(addon_zip_stream)
                                break

                            directory_range_response.raise_for_status()

                        else:
                            addon_zip_stream.seek(
                                extract_byte_range_offset(
                                    directory_range_response.headers[hdrs.CONTENT_RANGE]
                                )
                            )
                            addon_zip_stream.write(await directory_range_response.read())

                            try:
                                dynamic_addon_zip = zipfile.ZipFile(addon_zip_stream)
                            except zipfile.BadZipFile:
                                continue
                            else:
                                break

                if dynamic_addon_zip is None:
                    logger.debug('directory marker not found')
                    continue

                toc_filenames = {
                    n
                    for n, h in find_addon_zip_tocs(f.filename for f in dynamic_addon_zip.filelist)
                    if h in candidate['name']  # Folder name is a substring of zip name.
                }
                if not toc_filenames:
                    continue

                game_flavour_from_toc_filename = any(
                    n.lower().endswith(
                        NORMALISED_FLAVOUR_TOC_SUFFIXES[self._manager.config.game_flavour]
                    )
                    for n in toc_filenames
                )
                if game_flavour_from_toc_filename:
                    matching_asset = candidate
                    break

                try:
                    main_toc_filename = min(
                        (
                            n
                            for n in toc_filenames
                            if not n.lower().endswith(
                                tuple(
                                    i for s in NORMALISED_FLAVOUR_TOC_SUFFIXES.values() for i in s
                                )
                            )
                        ),
                        key=len,
                    )
                except ValueError:
                    continue

                if not is_zip_complete:
                    a, b = tee(dynamic_addon_zip.filelist)
                    next(b, None)
                    main_toc_file_offset, following_file = next(
                        (f.header_offset, n)
                        for f, n in zip_longest(a, b)
                        if f.filename == main_toc_filename
                    )
                    # If this is the last file in the list, download to eof. In theory,
                    # we could detect where the zip directory starts.
                    following_file_offset = following_file.header_offset if following_file else ''

                    logger.debug(f'fetching {main_toc_filename} from {candidate["name"]}')
                    async with self._manager.web_client.get(
                        candidate['browser_download_url'],
                        {'days': 30},
                        headers={
                            **github_headers,
                            hdrs.RANGE: f'bytes={main_toc_file_offset}-{following_file_offset}',
                        },
                        raise_for_status=True,
                    ) as toc_file_range_response:
                        addon_zip_stream.seek(main_toc_file_offset)
                        addon_zip_stream.write(await toc_file_range_response.read())

                toc_file_text = dynamic_addon_zip.read(main_toc_filename).decode('utf-8-sig')
                toc_reader = TocReader(toc_file_text)
                interface_version = toc_reader['Interface']
                logger.debug(
                    f'found interface version {interface_version!r} in {main_toc_filename}'
                )
                if interface_version and self._manager.config.game_flavour.to_flavour_keyed_enum(
                    FlavourVersion
                ).is_within_version(int(interface_version)):
                    matching_asset = candidate
                    break

            else:
                raise R.PkgFileUnavailable(
                    f'no files matching {self._manager.config.game_flavour}'
                )

        else:
            async with self._manager.web_client.get(
                release_json['browser_download_url'],
                {'days': 1},
                headers=github_headers,
                raise_for_status=True,
            ) as response:
                packager_metadata: _PackagerReleaseJson = await response.json()

            releases = packager_metadata['releases']
            if not releases:
                raise R.PkgFileUnavailable('no files available for download')

            wanted_flavour = self._manager.config.game_flavour.to_flavour_keyed_enum(
                _PackagerReleaseJsonFlavor
            )
            matching_release = next(
                (
                    r
                    for r in releases
                    if r['nolib'] is False
                    and any(m['flavor'] == wanted_flavour for m in r['metadata'])
                ),
                None,
            )
            if matching_release is None:
                raise R.PkgFileUnavailable(
                    f'no files matching {self._manager.config.game_flavour}'
                )

            matching_asset = next(
                (
                    a
                    for a in assets
                    if a['name'] == matching_release['filename'] and a['state'] == 'uploaded'
                ),
                None,
            )
            if matching_asset is None:
                raise R.PkgFileUnavailable(f'{matching_release["filename"]} not found')

        return models.Pkg(
            source=self.metadata.id,
            id=project_metadata['full_name'],
            slug=project_metadata['full_name'].lower(),
            name=project_metadata['name'],
            description=project_metadata['description'] or '',
            url=project_metadata['html_url'],
            download_url=matching_asset['browser_download_url'],
            date_published=iso8601.parse_date(release_metadata['published_at']),
            version=release_metadata['tag_name'],
            changelog_url=_format_data_changelog(release_metadata['body']),
            options=models.PkgOptions(
                strategy=defn.strategy,
            ),
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        import csv
        from io import StringIO

        logger.debug(f'retrieving {cls._generated_catalogue_csv_url}')
        async with web_client.get(
            cls._generated_catalogue_csv_url, raise_for_status=True
        ) as response:
            catalogue_csv = await response.text()

        for entry in csv.DictReader(StringIO(catalogue_csv)):
            yield BaseCatalogueEntry(
                source=cls.metadata.id,
                id=entry['full_name'],
                slug=entry['full_name'].lower(),
                name=entry['name'],
                url=entry['url'],
                game_flavours=frozenset(
                    Flavour.from_flavour_keyed_enum(_PackagerReleaseJsonFlavor(f))
                    for f in entry['flavors'].split(',')
                    if f
                ),
                download_count=1,
                last_updated=datetime.fromisoformat(entry['last_updated']),
                same_as=[
                    CatalogueSameAs(source=i, id=v)
                    for i in ['curse', 'wowi']
                    for v in (entry[f'{i}_id'],)
                    if v
                ],
            )


class InstawowResolver(BaseResolver):
    metadata = SourceMetadata(
        id='instawow',
        name='instawow',
        strategies=frozenset({Strategy.default}),
        changelog_format=ChangelogFormat.markdown,
    )

    _addons = {
        ('0', 'weakauras-companion'),
        ('1', 'weakauras-companion-autoupdate'),
    }

    async def resolve_one(self, defn: Defn, metadata: None) -> models.Pkg:
        try:
            source_id, slug = next(p for p in self._addons if defn.alias in p)
        except StopIteration:
            raise R.PkgNonexistent

        from .wa_updater import WaCompanionBuilder

        builder = WaCompanionBuilder(self._manager)
        if source_id == '1':
            await builder.build()

        return models.Pkg(
            source=self.metadata.id,
            id=source_id,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            download_url=builder.addon_zip_path.as_uri(),
            date_published=datetime.now(timezone.utc),
            version=await run_in_thread(builder.get_version)(),
            changelog_url=builder.changelog_path.as_uri(),
            options=models.PkgOptions(strategy=defn.strategy),
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
        yield BaseCatalogueEntry(
            source=cls.metadata.id,
            id='1',
            slug='weakauras-companion-autoupdate',
            name='WeakAuras Companion',
            url='https://github.com/layday/instawow',
            game_flavours=frozenset(Flavour),
            download_count=1,
            last_updated=datetime.now(timezone.utc),
            folders=[
                frozenset({'WeakAurasCompanion'}),
            ],
        )
