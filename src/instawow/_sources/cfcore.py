from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Generator, Sequence
from datetime import timedelta
from enum import IntEnum
from functools import partial
from typing import Generic, TypeVar

import iso8601
from loguru import logger
from typing_extensions import NotRequired as N
from typing_extensions import TypedDict
from yarl import URL

from .. import pkg_models
from .. import results as R
from ..catalogue.cataloguer import CatalogueEntry
from ..common import ChangelogFormat, Defn, Flavour, SourceMetadata, Strategy
from ..config import GlobalConfig
from ..http import CACHE_INDEFINITELY, ClientSessionType, make_generic_progress_ctx
from ..resolvers import BaseResolver, HeadersIntent, PkgCandidate
from ..utils import gather, uniq

_T = TypeVar('_T')


_CF_WOW_GAME_ID = 1


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
    "Extracted from https://api.curseforge.com/v1/games/1/version-types."

    Retail = 517
    VanillaClassic = 67408
    Classic = 73713


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
    downloadUrl: str | None  # null if distribution is forbidden
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


class _CfCoreResponsePagination(TypedDict):
    index: int
    pageSize: int
    resultCount: int
    totalCount: int | None


class _CfCorePaginatedResponse(TypedDict, Generic[_T]):
    data: _T
    pagination: _CfCoreResponsePagination


class _CfCoreStringDataResponse(TypedDict):
    data: str


class _CfCoreUnpaginatedModsResponse(TypedDict):
    data: list[_CfCoreMod]


class _CfCoreModsResponse(_CfCorePaginatedResponse['list[_CfCoreMod]']):
    pass


class _CfCoreFilesResponse(_CfCorePaginatedResponse['list[_CfCoreFile]']):
    pass


class CfCoreResolver(BaseResolver):
    metadata = SourceMetadata(
        id='curse',
        name='CFCore',
        strategies=frozenset(
            {
                Strategy.AnyReleaseType,
                Strategy.AnyFlavour,
                Strategy.VersionEq,
            }
        ),
        changelog_format=ChangelogFormat.Html,
        addon_toc_key='X-Curse-Project-ID',
    )
    requires_access_token = 'cfcore'

    # Ref: https://docs.curseforge.com/
    __mod_api_url = URL('https://api.curseforge.com/v1/mods')

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if (
            url.host == 'www.curseforge.com'
            and len(url.parts) > 3
            and url.parts[1:3] == ('wow', 'addons')
        ):
            return url.parts[3].lower()

    async def make_request_headers(
        self, intent: HeadersIntent | None = None
    ) -> dict[str, str] | None:
        if intent is HeadersIntent.Download:
            return None

        maybe_access_token = self._get_access_token(self._manager_ctx.config.global_config)
        if maybe_access_token is None:
            raise ValueError(f'{self.metadata.name} access token is not configured')
        return {'x-api-key': maybe_access_token}

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, pkg_models.Pkg | R.ManagerError | R.InternalError]:
        numeric_ids = uniq(i for d in defns if (i := d.id or d.alias).isdigit())
        if not numeric_ids:
            return await super().resolve(defns)  # Fast path.

        async with self._manager_ctx.web_client.post(
            self.__mod_api_url,
            expire_after=timedelta(minutes=5),
            headers=await self.make_request_headers(),
            json={'modIds': numeric_ids},
            raise_for_status=True,
        ) as response:
            response_json: _CfCoreUnpaginatedModsResponse = await response.json()

        addons_by_id = {str(r['id']): r for r in response_json['data']}

        results = await gather(
            (self.resolve_one(d, addons_by_id.get(d.id or d.alias)) for d in defns),
            R.resultify_async_exc,
        )
        return dict(zip(defns, results))

    async def _resolve_one(self, defn: Defn, metadata: _CfCoreMod | None) -> PkgCandidate:
        if metadata is None:
            if defn.alias.isdigit():
                async with self._manager_ctx.web_client.get(
                    self.__mod_api_url / defn.alias,
                    expire_after=timedelta(minutes=15),
                    headers=await self.make_request_headers(),
                ) as mod_response:
                    if mod_response.status == 404:
                        raise R.PkgNonexistent

                    mod_response.raise_for_status()

                    metadata = await mod_response.json()
                    assert metadata

            else:
                async with self._manager_ctx.web_client.get(
                    (self.__mod_api_url / 'search').with_query(
                        gameId=_CF_WOW_GAME_ID, slug=defn.alias
                    ),
                    expire_after=timedelta(minutes=15),
                    headers=await self.make_request_headers(),
                    raise_for_status=True,
                ) as mod_response:
                    mod_response_json: _CfCoreModsResponse = await mod_response.json()
                    if not mod_response_json['data']:
                        raise R.PkgNonexistent

                    [metadata] = mod_response_json['data']

        if defn.strategies.version_eq:
            game_version_type_id = self._manager_ctx.config.game_flavour.to_flavour_keyed_enum(
                _CfCoreSortableGameVersionTypeId
            )
            files_url = (self.__mod_api_url / str(metadata['id']) / 'files').with_query(
                gameVersionTypeId=game_version_type_id, pageSize=999
            )
            async with self._manager_ctx.web_client.get(
                files_url,
                expire_after=timedelta(hours=1),
                headers=await self.make_request_headers(),
                raise_for_status=True,
                trace_request_ctx=make_generic_progress_ctx(
                    f'Fetching metadata from {self.metadata.name}'
                ),
            ) as files_response:
                files_response_json: _CfCoreFilesResponse = await files_response.json()

            files = files_response_json['data']

        else:
            files = metadata['latestFiles']

        if not files:
            raise R.PkgFilesMissing

        def make_filter_fns() -> Generator[Callable[[_CfCoreFile], bool], None, None]:
            yield lambda f: not f.get('exposeAsAlternative', False)

            if not defn.strategies.any_flavour:
                type_id = self._manager_ctx.config.game_flavour.to_flavour_keyed_enum(
                    _CfCoreSortableGameVersionTypeId
                )
                yield lambda f: any(
                    s['gameVersionTypeId'] == type_id for s in f['sortableGameVersions']
                )

            if not defn.strategies.any_release_type:
                yield lambda f: f['releaseType'] == _CfCoreFileReleaseType.release

            if defn.strategies.version_eq:
                yield lambda f: f['displayName'] == defn.strategies.version_eq

        filter_fns = list(make_filter_fns())

        file = max(
            (f for f in files if all(r(f) for r in filter_fns)),
            # The ``id`` is just a counter so we don't have to go digging around dates
            key=lambda f: f['id'],
            default=None,
        )
        if file is None:
            raise R.PkgFilesNotMatching(defn.strategies)

        if file['downloadUrl'] is None:
            if metadata['allowModDistribution'] is False:
                raise R.PkgFilesMissing('package distribution is forbidden')
            else:
                raise R.PkgFilesMissing

        return PkgCandidate(
            id=str(metadata['id']),
            slug=metadata['slug'],
            name=metadata['name'],
            description=metadata['summary'],
            url=metadata['links']['websiteUrl'],
            download_url=file['downloadUrl'],
            date_published=iso8601.parse_date(file['fileDate']),
            version=file['displayName'],
            changelog_url=str(
                self.__mod_api_url / f'{metadata["id"]}/files/{file["id"]}/changelog'
            ),
            deps=[
                pkg_models.PkgDep(id=str(d['modId']))
                for d in file['dependencies']
                if d['relationType'] == _CfCoreFileRelationType.required_dependency
            ],
        )

    async def get_changelog(self, uri: URL) -> str:
        async with self._manager_ctx.web_client.get(
            uri,
            expire_after=CACHE_INDEFINITELY,
            headers=await self.make_request_headers(),
            raise_for_status=True,
        ) as response:
            response_json: _CfCoreStringDataResponse = await response.json()
            return response_json['data']

    @classmethod
    async def catalogue(cls, web_client: ClientSessionType) -> AsyncIterator[CatalogueEntry]:
        from aiohttp import ClientTimeout

        flavours_and_version_types = [
            (f, f.to_flavour_keyed_enum(_CfCoreSortableGameVersionTypeId)) for f in Flavour
        ]

        def excise_flavours(files: list[_CfCoreFile]):
            for flavour, version_type in flavours_and_version_types:
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
            web_client.get,
            headers={'x-api-key': cls._get_access_token(GlobalConfig.from_values(env=True))},
            raise_for_status=True,
            timeout=ClientTimeout(total=10),
        )

        for offset in range(0, MAX_OFFSET, STEP):
            url = (cls.__mod_api_url / 'search').with_query(
                gameId=_CF_WOW_GAME_ID,
                sortField=_CfCoreModsSearchSortField.last_updated,
                sortOrder='desc',
                pageSize=STEP,
                index=offset,
            )
            logger.debug(f'retrieving {url}')

            for attempt in range(3):
                try:
                    async with get(url) as response:
                        response_json: _CfCoreModsResponse = await response.json()
                        break
                except asyncio.TimeoutError:
                    logger.debug(f'request timed out; attempt {attempt + 1} of 3')
            else:
                raise RuntimeError('maximum number of attempts exceeded')

            items = response_json['data']
            if not items:
                break

            for item in items:
                yield CatalogueEntry(
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
