from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from datetime import timedelta
from enum import IntEnum
from functools import partial
from typing import Generic, TypeVar

from typing_extensions import NotRequired as N
from typing_extensions import TypedDict
from yarl import URL

from .. import http, pkg_models, shared_ctx
from .. import results as R
from .._logging import logger
from .._progress_reporting import make_default_progress
from .._utils.aio import gather
from .._utils.datetime import datetime_fromisoformat
from .._utils.iteration import uniq
from ..catalogue.cataloguer import CatalogueEntry
from ..config import GlobalConfig
from ..definitions import ChangelogFormat, Defn, SourceMetadata, Strategy
from ..resolvers import BaseResolver, HeadersIntent, PkgCandidate
from ..wow_installations import Flavour
from ._access_tokens import AccessToken

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
    Classic = 77522
    WrathClassic = 73713


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


class _CfCoreDataResponse(TypedDict, Generic[_T]):
    data: _T


class _CfCorePaginatedDataResponse(TypedDict, Generic[_T]):
    data: _T
    pagination: _CfCoreResponsePagination


_VERSION_SEP = '_'


class CfCoreResolver(BaseResolver):
    metadata = SourceMetadata(
        id='curse',
        name='CFCore',
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
    access_token = AccessToken('cfcore', True)

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

    def make_request_headers(self, intent: HeadersIntent | None = None) -> dict[str, str] | None:
        if intent is HeadersIntent.Download:
            return None
        return {'x-api-key': self.access_token.get()}

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, pkg_models.Pkg | R.ManagerError | R.InternalError]:
        numeric_ids = uniq(i for d in defns if (i := d.id or d.alias).isdigit())
        if not numeric_ids:
            return await super().resolve(defns)  # Fast path.

        async with shared_ctx.web_client.post(
            self.__mod_api_url,
            expire_after=timedelta(minutes=5),
            headers=self.make_request_headers(),
            json={'modIds': numeric_ids},
            raise_for_status=True,
        ) as response:
            response_json: _CfCoreDataResponse[list[_CfCoreMod]] = await response.json()

        addons_by_id = {str(r['id']): r for r in response_json['data']}

        results = await gather(
            R.resultify_async_exc(self.resolve_one(d, addons_by_id.get(d.id or d.alias)))
            for d in defns
        )
        return dict(zip(defns, results))

    async def _resolve_one(self, defn: Defn, metadata: _CfCoreMod | None) -> PkgCandidate:
        if metadata is None:
            if defn.alias.isdigit():
                async with shared_ctx.web_client.get(
                    self.__mod_api_url / defn.alias,
                    expire_after=timedelta(minutes=15),
                    headers=self.make_request_headers(),
                ) as mod_response:
                    if mod_response.status == 404:
                        raise R.PkgNonexistent

                    mod_response.raise_for_status()

                    metadata = await mod_response.json()
                    assert metadata

            else:
                async with shared_ctx.web_client.get(
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
                        raise R.PkgNonexistent

                    [metadata] = mod_response_json['data']

        version_eq = defn.strategies[Strategy.VersionEq]
        if version_eq:
            _, file_sep, file_id = version_eq.rpartition(_VERSION_SEP)
            files_url = self.__mod_api_url / str(metadata['id']) / 'files'
            if file_sep:
                files_url /= file_id

            async with shared_ctx.web_client.get(
                files_url,
                expire_after=timedelta(hours=1),
                headers=self.make_request_headers(),
                raise_for_status=True,
                trace_request_ctx={
                    'progress': make_default_progress(
                        type_='download', label=f'Fetching metadata from {self.metadata.name}'
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
            raise R.PkgFilesMissing

        # Allow pre-releases only if no stable releases exist or explicitly opted into.
        any_release_type = True
        if not defn.strategies[Strategy.AnyReleaseType]:
            any_release_type = not any(
                f['releaseType'] == _CfCoreFileReleaseType.release for f in files
            )

        desired_flavour_groups = self._config.game_flavour.get_flavour_groups(
            bool(defn.strategies[Strategy.AnyFlavour])
        )
        for desired_flavours in desired_flavour_groups:

            def make_filter_fns(
                desired_flavours: Sequence[Flavour] | None,
            ) -> Iterator[Callable[[_CfCoreFile], bool]]:
                yield lambda f: not f.get('exposeAsAlternative', False)

                if desired_flavours:
                    type_ids = {
                        f.to_flavour_keyed_enum(_CfCoreSortableGameVersionTypeId)
                        for f in desired_flavours
                    }
                    yield lambda f: any(
                        s['gameVersionTypeId'] in type_ids for s in f['sortableGameVersions']
                    )

                if not any_release_type:
                    yield lambda f: f['releaseType'] == _CfCoreFileReleaseType.release

            filter_fns = list(make_filter_fns(desired_flavours))
            try:
                file = max(
                    (f for f in files if all(r(f) for r in filter_fns)),
                    # The ``id`` is just a counter so we don't have to go digging around dates
                    key=lambda f: f['id'],
                )
            except ValueError:
                continue
            break

        else:
            raise R.PkgFilesNotMatching(defn.strategies)

        if file['downloadUrl'] is None:
            raise (
                R.PkgFilesMissing('package distribution is forbidden')
                if metadata['allowModDistribution'] is False
                else R.PkgFilesMissing
            )

        return PkgCandidate(
            id=str(metadata['id']),
            slug=metadata['slug'],
            name=metadata['name'],
            description=metadata['summary'],
            url=metadata['links']['websiteUrl'],
            download_url=file['downloadUrl'],
            date_published=datetime_fromisoformat(file['fileDate']),
            version=f'{file["displayName"]}{_VERSION_SEP}{file["id"]}',
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
        async with shared_ctx.web_client.get(
            uri,
            expire_after=http.CACHE_INDEFINITELY,
            headers=self.make_request_headers(),
            raise_for_status=True,
        ) as response:
            response_json: _CfCoreDataResponse[str] = await response.json()
            return response_json['data']

    @classmethod
    async def catalogue(cls) -> AsyncIterator[CatalogueEntry]:
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
            shared_ctx.web_client.get,
            headers={'x-api-key': cls.access_token.get(GlobalConfig.from_values(env=True))},
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
                        response_json: _CfCorePaginatedDataResponse[
                            list[_CfCoreMod]
                        ] = await response.json()
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
                    last_updated=datetime_fromisoformat(item['dateReleased']),
                    folders=excise_folders(item['latestFiles']),
                )
