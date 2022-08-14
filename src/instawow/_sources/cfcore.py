from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from enum import IntEnum
from itertools import count
from typing import Generic, TypeVar

import iso8601
from loguru import logger
from typing_extensions import NotRequired as N, TypedDict
from yarl import URL

from .. import _deferred_types, manager, models, results as R
from ..cataloguer import BaseCatalogueEntry
from ..common import ChangelogFormat, Flavour, SourceMetadata, Strategy
from ..config import GlobalConfig
from ..resolvers import BaseResolver, Defn
from ..utils import gather, uniq

_T = TypeVar('_T')


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

    retail = 517
    vanilla_classic = 67408
    burning_crusade_classic = 73246
    wrath_classic = 73713


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
            raise ValueError(f'{cls.metadata.name} access token not configured')
        return maybe_access_token

    async def make_auth_headers(self) -> dict[str, str] | None:
        return {'x-api-key': self._get_access_token(self._manager.config.global_config)}

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
            headers=await self.make_auth_headers(),
            json={'modIds': numeric_ids},
        ) as response:
            if response.status == 404:
                return await super().resolve(defns)

            response.raise_for_status()
            response_json: _CfCoreUnpaginatedModsResponse = await response.json()

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
                headers=await self.make_auth_headers(),
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

        if file['downloadUrl'] is None:
            if metadata['allowModDistribution'] is False:
                raise R.PkgFileUnavailable('package distribution is forbidden')
            else:
                raise R.PkgFileUnavailable

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
        async with self._manager.web_client.get(
            uri, {'days': 1}, headers=await self.make_auth_headers(), raise_for_status=True
        ) as response:
            response_json: _CfCoreStringDataResponse = await response.json()
            return response_json['data']

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatalogueEntry]:
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
