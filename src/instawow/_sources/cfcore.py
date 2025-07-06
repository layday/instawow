from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime, timedelta
from enum import IntEnum
from functools import partial
from typing import NotRequired

from typing_extensions import TypedDict
from yarl import URL

from .. import config_ctx, http, http_ctx
from .._logging import logger
from .._utils.aio import gather
from .._utils.iteration import uniq
from ..definitions import ChangelogFormat, Defn, SourceMetadata, Strategy
from ..progress_reporting import make_download_progress
from ..resolvers import (
    AccessToken,
    BaseResolver,
    CatalogueEntryCandidate,
    HeadersIntent,
    PkgCandidate,
)
from ..results import PkgFilesMissing, PkgFilesNotMatching, PkgNonexistent, resultify
from ..wow_installations import Flavour, get_compatible_flavours, to_flavourful_enum

_CF_WOW_GAME_ID = 1


class _CfCoreModLinks(TypedDict):
    websiteUrl: str
    wikiUrl: str
    issuesUrl: str
    sourceUrl: str


class _CfCoreModStatus(IntEnum):
    New = 1
    ChangesRequired = 2
    UnderSoftReview = 3
    Approved = 4
    Rejected = 5
    ChangesMade = 6
    Inactive = 7
    Abandoned = 8
    Deleted = 9
    UnderReview = 10


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
    Processing = 1
    ChangesRequired = 2
    UnderReview = 3
    Approved = 4
    Rejected = 5
    MalwareDetected = 6
    Deleted = 7
    Archived = 8
    Testing = 9
    Released = 10
    ReadyForReview = 11
    Deprecated = 12
    Baking = 13
    AwaitingPublishing = 14
    FailedPublishing = 15


class _CfCoreFileReleaseType(IntEnum):
    Release = 1
    Beta = 2
    Alpha = 3


class _CfCoreHashAlgo(IntEnum):
    Sha1 = 1
    Md5 = 2


class _CfCoreFileHash(TypedDict):
    value: str
    algo: _CfCoreHashAlgo


class _CfCoreSortableGameVersionTypeId(IntEnum):
    "Extracted from https://api.curseforge.com/v1/games/1/version-types."

    Retail = 517
    VanillaClassic = 67408
    TbcClassic = 73246
    WrathClassic = 73713
    CataClassic = 77522
    MistsClassic = 79434


class _CfCoreSortableGameVersion(TypedDict):
    gameVersionName: str
    gameVersionPadded: str
    gameVersion: str
    gameVersionReleaseDate: str  # date-time
    gameVersionTypeId: _CfCoreSortableGameVersionTypeId


class _CfCoreFileRelationType(IntEnum):
    EmbeddedLibrary = 1
    OptionalDependency = 2
    RequiredDependency = 3
    Tool = 4
    Incompatible = 5
    Include = 6


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
    downloadUrl: str | None  # null if distribution is forbidden
    gameVersions: list[str]
    sortableGameVersions: list[_CfCoreSortableGameVersion]
    dependencies: list[_CfCoreFileDependency]
    exposeAsAlternative: NotRequired[bool]
    parentProjectFileId: NotRequired[int]
    alternateFileId: int
    isServerPack: bool
    serverPackFileId: NotRequired[int]
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
    Featured = 1
    Popularity = 2
    LastUpdated = 3
    Name = 4
    Author = 5
    TotalDownloads = 6
    Category = 7
    GameVersion = 8
    EarlyAccess = 9
    FeaturedReleased = 10
    ReleasedDate = 11
    Rating = 12


class _CfCoreResponsePagination(TypedDict):
    index: int
    pageSize: int
    resultCount: int
    totalCount: int | None


class _CfCoreDataResponse[T](TypedDict):
    data: T


class _CfCorePaginatedDataResponse[T](TypedDict):
    data: T
    pagination: _CfCoreResponsePagination


_ALTERNATIVE_API_URL_ENV_KEY = 'INSTAWOW_CF_API_URL'
_alternative_api_url = os.environ.get(_ALTERNATIVE_API_URL_ENV_KEY)


_VERSION_SEP = '_'


class CfCoreResolver(BaseResolver[_CfCoreMod]):
    metadata = SourceMetadata(
        id='curse',
        name='CurseForge',
        strategies=frozenset(
            {
                Strategy.AnyFlavour,
                Strategy.AnyReleaseType,
                Strategy.VersionEq,
            }
        ),
        changelog_format=ChangelogFormat.Html,
        addon_toc_key='X-Curse-Project-ID',
    )

    # Ref: https://docs.curseforge.com/
    __mod_api_url = URL(_alternative_api_url or 'https://api.curseforge.com/v1').joinpath('mods')

    @AccessToken
    def access_token():
        return config_ctx.config().global_config.access_tokens.cfcore, not _alternative_api_url

    def get_alias_from_url(self, url: URL):
        if (
            url.host == 'www.curseforge.com'
            and len(url.parts) > 3
            and url.parts[1:3] == ('wow', 'addons')
        ):
            return url.parts[3].lower()

    def make_request_headers(self, intent: HeadersIntent | None = None):
        if not _alternative_api_url and intent is not HeadersIntent.Download:
            maybe_access_token = self.access_token.get()
            if maybe_access_token:
                return {'x-api-key': maybe_access_token}

    async def resolve(self, defns: Sequence[Defn]):
        defn_ids = {d: d.id or d.alias for d in defns}
        numeric_ids = uniq(i for i in defn_ids.values() if i.isdigit())
        if not numeric_ids:
            return await super().resolve(defns)  # Fast path.

        async with http_ctx.web_client().post(
            self.__mod_api_url,
            expire_after=timedelta(minutes=5),
            headers=self.make_request_headers(),
            json={'modIds': numeric_ids},
            raise_for_status=True,
        ) as response:
            response_json: _CfCoreDataResponse[list[_CfCoreMod]] = await response.json()

        addons_by_id = {str(r['id']): r for r in response_json['data']}

        resolve_one = resultify(self.resolve_one)
        results = await gather(resolve_one(d, addons_by_id.get(i)) for d, i in defn_ids.items())
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: _CfCoreMod | None):
        if metadata is None:
            if defn.alias.isdigit():
                async with http_ctx.web_client().get(
                    self.__mod_api_url / defn.alias,
                    expire_after=timedelta(minutes=15),
                    headers=self.make_request_headers(),
                ) as mod_response:
                    if mod_response.status == 404:
                        raise PkgNonexistent

                    mod_response.raise_for_status()

                    metadata = await mod_response.json()
                    assert metadata

            else:
                async with http_ctx.web_client().get(
                    (self.__mod_api_url / 'search').with_query(
                        gameId=_CF_WOW_GAME_ID, slug=defn.alias
                    ),
                    expire_after=timedelta(minutes=15),
                    headers=self.make_request_headers(),
                    raise_for_status=True,
                ) as mod_response:
                    mod_response_json: _CfCorePaginatedDataResponse[
                        list[_CfCoreMod]
                    ] = await mod_response.json()
                    if not mod_response_json['data']:
                        raise PkgNonexistent

                    [metadata] = mod_response_json['data']

        version_eq = defn.strategies[Strategy.VersionEq]
        if version_eq:
            _, file_sep, file_id = version_eq.rpartition(_VERSION_SEP)
            files_url = self.__mod_api_url / str(metadata['id']) / 'files'
            if file_sep and file_id:
                files_url /= file_id

            async with http_ctx.web_client().get(
                files_url,
                expire_after=timedelta(hours=1),
                headers=self.make_request_headers(),
                raise_for_status=True,
                trace_request_ctx={
                    'progress': make_download_progress(
                        label=f'Fetching metadata from {self.metadata.name}'
                    )
                },
            ) as files_response:
                files_response_json: (
                    _CfCoreDataResponse[_CfCoreFile] | _CfCoreDataResponse[list[_CfCoreFile]]
                ) = await files_response.json()

            files = files_response_json['data']
            if isinstance(files, list):
                files = next(
                    ([f] for f in files if f['displayName'] == version_eq), list[_CfCoreFile]()
                )
            else:
                files = [files]

        else:
            files = metadata['latestFiles']

        if not files:
            raise PkgFilesMissing

        files = [f for f in files if not f.get('exposeAsAlternative')]

        # Allow pre-releases only if no stable releases exist or explicitly opted into.
        if not defn.strategies[Strategy.AnyReleaseType] and any(
            f['releaseType'] == _CfCoreFileReleaseType.Release for f in files
        ):
            files = [f for f in files if f['releaseType'] == _CfCoreFileReleaseType.Release]

        desired_flavours = get_compatible_flavours(
            config_ctx.config().track, defn.strategies[Strategy.AnyFlavour]
        )
        for desired_flavour in desired_flavours:
            if desired_flavour:
                type_id = to_flavourful_enum(desired_flavour, _CfCoreSortableGameVersionTypeId)
                shortlisted_files = (
                    f
                    for f in files
                    if any(s['gameVersionTypeId'] == type_id for s in f['sortableGameVersions'])
                )
            else:
                shortlisted_files = files

            try:
                file = max(
                    shortlisted_files,
                    # The ``id`` is just a counter so we don't have to go digging around dates
                    key=lambda f: f['id'],
                )
            except ValueError:
                continue
            break

        else:
            raise PkgFilesNotMatching(defn.strategies)

        if file['downloadUrl'] is None:
            raise (
                PkgFilesMissing('package distribution is forbidden')
                if metadata['allowModDistribution'] is False
                else PkgFilesMissing
            )

        return PkgCandidate(
            id=str(metadata['id']),
            slug=metadata['slug'],
            name=metadata['name'],
            description=metadata['summary'],
            url=metadata['links']['websiteUrl'],
            download_url=file['downloadUrl'],
            date_published=datetime.fromisoformat(file['fileDate']),
            version=f'{file["displayName"]}{_VERSION_SEP}{file["id"]}',
            changelog_url=str(
                self.__mod_api_url / f'{metadata["id"]}/files/{file["id"]}/changelog'
            ),
            deps=[
                {'id': str(d['modId'])}
                for d in file['dependencies']
                if d['relationType'] == _CfCoreFileRelationType.RequiredDependency
            ],
        )

    async def get_changelog(self, uri: URL):
        async with http_ctx.web_client().get(
            uri,
            expire_after=http.CACHE_INDEFINITELY,
            headers=self.make_request_headers(),
            raise_for_status=True,
        ) as response:
            response_json: _CfCoreDataResponse[str] = await response.json()
            return response_json['data']

    async def catalogue(self):
        from aiohttp import ClientTimeout

        supported_flavours = [
            (f, to_flavourful_enum(f, _CfCoreSortableGameVersionTypeId)) for f in Flavour
        ]

        def excise_flavours(files: list[_CfCoreFile]):
            for flavour, version_type in supported_flavours:
                if any(
                    not f.get('exposeAsAlternative', False)
                    and any(
                        s['gameVersionTypeId'] == version_type for s in f['sortableGameVersions']
                    )
                    for f in files
                ):
                    yield flavour

        def excise_folders(files: list[_CfCoreFile]):
            return uniq(frozenset(m['name'] for m in f['modules']) for f in files)

        STEP = 50
        MAX_OFFSET = 10_000  # The CF API craps out after 9,999 results

        get = partial(
            http_ctx.web_client().get,
            raise_for_status=True,
            timeout=ClientTimeout(total=10),
        )
        access_token = self.access_token.get()
        if access_token:
            get = partial(get, headers={'x-api-key': access_token})

        for offset in range(0, MAX_OFFSET, STEP):
            url = (self.__mod_api_url / 'search').with_query(
                gameId=_CF_WOW_GAME_ID,
                sortField=_CfCoreModsSearchSortField.LastUpdated,
                sortOrder='desc',
                pageSize=STEP,
                index=offset,
            )
            logger.debug(f'Retrieving {url}')

            for attempt in range(3):
                try:
                    async with get(url) as response:
                        response_json: _CfCorePaginatedDataResponse[
                            list[_CfCoreMod]
                        ] = await response.json()
                        break
                except TimeoutError:
                    logger.debug(f'Request timed out; attempt {attempt + 1} of 3')
            else:
                raise RuntimeError('Maximum number of attempts exceeded')

            items = response_json['data']
            if not items:
                break

            for item in items:
                yield CatalogueEntryCandidate(
                    id=str(item['id']),
                    slug=item['slug'],
                    name=item['name'],
                    url=item['links']['websiteUrl'],
                    game_flavours=frozenset(excise_flavours(item['latestFiles'])),
                    download_count=item['downloadCount'],
                    last_updated=datetime.fromisoformat(item['dateReleased']),
                    folders=excise_folders(item['latestFiles']),
                )
