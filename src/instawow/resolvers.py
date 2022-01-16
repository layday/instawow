from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence, Set
from datetime import datetime, timezone
from enum import IntEnum
from functools import partial
from itertools import count, takewhile
import re
import typing
from typing import Any, ClassVar

from loguru import logger
from pydantic import BaseModel
from typing_extensions import Literal
from typing_extensions import NotRequired as N
from typing_extensions import Protocol, TypedDict
from yarl import URL

from . import _deferred_types, manager, models
from . import results as R
from .cataloguer import BaseCatatalogueEntry
from .common import ChangelogFormat, Flavour, Strategy
from .config import GlobalConfig
from .utils import StrEnum, evolve_model_obj, gather, normalise_names, uniq


class Defn(BaseModel, frozen=True):
    source: str
    id: typing.Optional[str] = None
    alias: str
    strategy: Strategy = Strategy.default
    version: typing.Optional[str] = None

    def __init__(self, source: str, alias: str, **kwargs: Any) -> None:
        super().__init__(source=source, alias=alias, **kwargs)

    @classmethod
    def from_pkg(cls, pkg: models.Pkg) -> Defn:
        return cls(
            pkg.source, pkg.slug, id=pkg.id, strategy=pkg.options.strategy, version=pkg.version
        )

    def with_version(self, version: str) -> Defn:
        return evolve_model_obj(self, strategy=Strategy.version, version=version)

    def to_urn(self) -> str:
        return f'{self.source}:{self.alias}'


slugify = normalise_names('-')


def _format_data_changelog(changelog: str = '') -> str:
    import urllib.parse

    return f'data:,{urllib.parse.quote(changelog)}'


class Resolver(Protocol):
    source: ClassVar[str]
    name: ClassVar[str]
    strategies: ClassVar[Set[Strategy]]
    changelog_format: ClassVar[ChangelogFormat]

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

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatatalogueEntry]:
        "Yield add-ons from source for cataloguing."
        return
        yield


class BaseResolver(Resolver):
    def __init__(self, manager: manager.Manager) -> None:
        self.manager = manager

    def __init_subclass__(cls) -> None:
        orig_resolve_one = cls.resolve_one

        async def resolve_one(self: BaseResolver, defn: Defn, metadata: Any) -> models.Pkg:
            if defn.strategy not in self.strategies:
                raise R.PkgStrategyUnsupported(defn.strategy)
            return await orig_resolve_one(self, defn, metadata)

        setattr(cls, 'resolve_one', resolve_one)

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

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatatalogueEntry]:
        return
        yield


class _CurseFlavor(StrEnum):
    retail = 'wow_retail'
    vanilla_classic = 'wow_classic'
    burning_crusade_classic = 'wow_burning_crusade'


class _CurseGameVersionTypeId(IntEnum):
    retail = 517
    vanilla_classic = 67408
    burning_crusade_classic = 73246


# Only documenting the fields we're actually using.
class _CurseAddon(TypedDict):
    id: int
    name: str  # User-facing add-on name
    websiteUrl: str  # e.g. 'https://www.curseforge.com/wow/addons/molinari'
    summary: str  # One-line description of the add-on
    downloadCount: int  # Total number of downloads
    latestFiles: list[_CurseAddon_File]
    gameVersionLatestFiles: list[_CurseAddon_GameVersionFile]
    slug: str  # URL slug; 'molinari' in 'https://www.curseforge.com/wow/addons/molinari'
    dateReleased: str  # ISO datetime of latest release


class _CurseAddon_File(TypedDict):
    id: int  # Unique file ID
    displayName: str  # Tends to be the version
    downloadUrl: str
    fileDate: str  # Upload datetime in ISO, e.g. '2020-02-02T12:12:12Z'
    releaseType: Literal[1, 2, 3]  # 1 = stable; 2 = beta; 3 = alpha
    dependencies: list[_CurseAddon_FileDependency]
    modules: list[_CurseAddon_FileModules]
    exposeAsAlternative: bool | None
    gameVersionFlavor: _CurseFlavor
    sortableGameVersion: list[_CurseAddon_FileSortableGameVersion]


class _CurseAddon_GameVersionFile(TypedDict):
    projectFileName: str
    gameVersionFlavor: _CurseFlavor
    gameVersionTypeId: N[_CurseGameVersionTypeId]


class _CurseAddon_FileDependency(TypedDict):
    id: int  # Unique dependency ID
    addonId: int  # The ID of the add-on we're depending on
    # The type of dependency.  One of:
    #   1 = embedded library
    #   2 = optional dependency
    #   3 = required dependency (this is the one we're after)
    #   4 = tool
    #   5 = incompatible
    #   6 = include (wat)
    type: Literal[1, 2, 3, 4, 5, 6]
    fileId: int  # The ID of the parent file which has this as a dependency


class _CurseAddon_FileModules(TypedDict):
    foldername: str
    fingerprint: int  # Folder fingerprint used by Curse for reconciliation
    # One of:
    #   1 = package
    #   2 = module
    #   3 = main module
    #   4 = file
    #   5 = referenced file
    # For WoW add-ons the main folder will have type "3" and the rest
    # of them type "2"
    type: Literal[1, 2, 3, 4, 5]


class _CurseAddon_FileSortableGameVersion(TypedDict):
    gameVersionTypeId: N[_CurseGameVersionTypeId]


class _CurseFile(TypedDict):
    id: int
    displayName: str
    downloadUrl: str
    fileDate: str  # Upload datetime in ISO, e.g. '2020-02-02T12:12:12Z'
    releaseType: Literal[1, 2, 3]  # 1 = stable; 2 = beta; 3 = alpha
    dependencies: list[_CurseAddon_FileDependency]
    modules: list[_CurseAddon_FileModules]
    gameVersionFlavor: _CurseFlavor


class CurseResolver(BaseResolver):
    source = 'curse'
    name = 'CurseForge'
    strategies = frozenset(
        {
            Strategy.default,
            Strategy.latest,
            Strategy.any_flavour,
            Strategy.version,
        }
    )
    changelog_format = ChangelogFormat.html

    addon_api_url = URL('https://addons-ecs.forgesvc.net/api/v2/addon')

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if (
            url.host == 'www.curseforge.com'
            and len(url.parts) > 3
            and url.parts[1:3] == ('wow', 'addons')
        ):
            return url.parts[3].lower()

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        catalogue = await self.manager.synchronise()

        defns_to_maybe_numeric_ids = {
            d: i if i.isdigit() else None
            for d in defns
            for i in (d.id or catalogue.curse_slugs.get(d.alias) or d.alias,)
        }
        async with self.manager.web_client.request(
            'POST',
            self.addon_api_url,
            {'minutes': 5},
            json=[i for i in defns_to_maybe_numeric_ids.values() if i is not None],
        ) as response:
            if response.status == 404:
                return await super().resolve(defns)
            else:
                response.raise_for_status()
                addons: list[_CurseAddon] = await response.json()

        numeric_ids_to_addons = {str(r['id']): r for r in addons}
        results = await gather(
            (
                self.resolve_one(d, numeric_ids_to_addons.get(i) if i is not None else i)
                for d, i in defns_to_maybe_numeric_ids.items()
            ),
            manager.capture_manager_exc_async,
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: _CurseAddon | None) -> models.Pkg:
        if metadata is None:
            raise R.PkgNonexistent

        if defn.strategy is Strategy.version:
            async with self.manager.web_client.get(
                self.addon_api_url / str(metadata['id']) / 'files',
                {'hours': 1},
                label=f'Fetching metadata from {self.name}',
                raise_for_status=True,
            ) as response:
                all_files: list[_CurseFile] = await response.json()

            file = next((f for f in all_files if defn.version == f['displayName']), None)
            if file is None:
                raise R.PkgFileUnavailable(f'version {defn.version} not found')

        else:
            latest_files = metadata['latestFiles']
            if not latest_files:
                raise R.PkgFileUnavailable('no files available for download')

            def make_filter():
                def is_not_libless(f: _CurseAddon_File):
                    # There's also an 'isAlternate' field that's missing from some
                    # 50 lib-less files from c. 2008.  'exposeAsAlternative' is
                    # absent from the /file endpoint
                    return not f['exposeAsAlternative']

                yield is_not_libless

                if defn.strategy is not Strategy.any_flavour:

                    curse_type_id = Flavour.to_flavour_keyed_enum(
                        _CurseGameVersionTypeId, self.manager.config.game_flavour
                    )

                    def supports_flavour(f: _CurseAddon_File):
                        return f['gameVersionFlavor'] == Flavour.to_flavour_keyed_enum(
                            _CurseFlavor, self.manager.config.game_flavour
                        ) or any(
                            s.get('gameVersionTypeId') == curse_type_id
                            for s in f['sortableGameVersion']
                        )

                    yield supports_flavour

                if defn.strategy is not Strategy.latest:

                    def is_stable_release(f: _CurseAddon_File):
                        return f['releaseType'] == 1

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
                    f'no files matching {self.manager.config.game_flavour} '
                    f'using {defn.strategy} strategy'
                )

        return models.Pkg.parse_obj(
            {
                'source': self.source,
                'id': metadata['id'],
                'slug': metadata['slug'],
                'name': metadata['name'],
                'description': metadata['summary'],
                'url': metadata['websiteUrl'],
                'download_url': file['downloadUrl'],
                'date_published': file['fileDate'],
                'version': file['displayName'],
                'changelog_url': str(
                    self.addon_api_url / f'{metadata["id"]}/file/{file["id"]}/changelog'
                ),
                'options': {'strategy': defn.strategy},
                'deps': [{'id': d['addonId']} for d in file['dependencies'] if d['type'] == 3],
            }
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatatalogueEntry]:
        def excise_flavours(files: list[_CurseAddon_File]):
            for flavour in Flavour:
                if any(
                    not f['exposeAsAlternative']
                    and (
                        f['gameVersionFlavor']
                        == Flavour.to_flavour_keyed_enum(_CurseFlavor, flavour)
                        or any(
                            s.get('gameVersionTypeId')
                            == Flavour.to_flavour_keyed_enum(_CurseGameVersionTypeId, flavour)
                            for s in f['sortableGameVersion']
                        )
                    )
                    for f in files
                ):
                    yield flavour

        def get_folders(files: list[_CurseAddon_File]):
            return uniq(frozenset(m['foldername'] for m in f['modules']) for f in files)

        step = 50
        sort_order = '3'  # Alphabetical
        for index in range(0, 10001 - step, step):
            # Try not to get rate limited
            await asyncio.sleep(2)

            url = (cls.addon_api_url / 'search').with_query(
                gameId='1', sort=sort_order, pageSize=step, index=index
            )
            logger.debug(f'retrieving {url}')
            async with web_client.get(url, raise_for_status=True) as response:
                items: list[_CurseAddon] = await response.json()

            if not items:
                break

            for item in items:
                yield BaseCatatalogueEntry.parse_obj(
                    {
                        'source': cls.source,
                        'id': item['id'],
                        'slug': item['slug'],
                        'name': item['name'],
                        'url': item['websiteUrl'],
                        'game_flavours': excise_flavours(item['latestFiles']),
                        'download_count': item['downloadCount'],
                        'last_updated': item['dateReleased'],
                        'folders': get_folders(item['latestFiles']),
                    }
                )


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


class _CfCoreModsSearchSortField(IntEnum):
    featured = 1
    popularity = 2
    last_updated = 3
    name_ = 4
    author = 5
    total_downloads = 6
    category = 7
    game_version = 8


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
    source = 'curse'
    name = 'CFCore'
    strategies = frozenset(
        {
            Strategy.default,
            Strategy.latest,
            Strategy.any_flavour,
            Strategy.version,
        }
    )
    changelog_format = ChangelogFormat.html

    # Ref: https://docs.curseforge.com/
    mod_api_url = URL('https://api.curseforge.com/v1/mods')

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
        return maybe_access_token.get_secret_value()

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        catalogue = await self.manager.synchronise()

        defns_to_maybe_numeric_ids = {
            d: i if i.isdigit() else None
            for d in defns
            for i in (d.id or catalogue.curse_slugs.get(d.alias) or d.alias,)
        }
        async with self.manager.web_client.request(
            'POST',
            self.mod_api_url,
            {'minutes': 5},
            headers={'x-api-key': self._get_access_token(self.manager.config.global_config)},
            json={'modIds': [i for i in defns_to_maybe_numeric_ids.values() if i is not None]},
        ) as response:
            if response.status == 404:
                return await super().resolve(defns)
            else:
                response.raise_for_status()
                response_json: _CfCoreModsResponseSansPagination = await response.json()

        numeric_ids_to_addons = {str(r['id']): r for r in response_json['data']}
        results = await gather(
            (
                self.resolve_one(d, numeric_ids_to_addons.get(i) if i is not None else i)
                for d, i in defns_to_maybe_numeric_ids.items()
            ),
            manager.capture_manager_exc_async,
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: _CfCoreMod | None) -> models.Pkg:
        if metadata is None:
            raise R.PkgNonexistent

        if defn.strategy is Strategy.version:
            async with self.manager.web_client.get(
                (self.mod_api_url / str(metadata['id']) / 'files').with_query(
                    gameVersionTypeId=Flavour.to_flavour_keyed_enum(
                        _CfCoreSortableGameVersionTypeId, self.manager.config.game_flavour
                    ),
                    pageSize=9999,
                ),
                {'hours': 1},
                headers={'x-api-key': self._get_access_token(self.manager.config.global_config)},
                label=f'Fetching metadata from {self.name}',
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

                    type_id = Flavour.to_flavour_keyed_enum(
                        _CfCoreSortableGameVersionTypeId, self.manager.config.game_flavour
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
                    f'no files matching {self.manager.config.game_flavour} '
                    f'using {defn.strategy} strategy'
                )

        return models.Pkg.parse_obj(
            {
                'source': self.source,
                'id': metadata['id'],
                'slug': metadata['slug'],
                'name': metadata['name'],
                'description': metadata['summary'],
                'url': metadata['links']['websiteUrl'],
                'download_url': file['downloadUrl'],
                'date_published': file['fileDate'],
                'version': file['displayName'],
                'changelog_url': str(
                    self.mod_api_url / f'{metadata["id"]}/file/{file["id"]}/changelog'
                ),
                'options': {'strategy': defn.strategy},
                'deps': [
                    {'id': d['modId']}
                    for d in file['dependencies']
                    if d['relationType'] == _CfCoreFileRelationType.required_dependency
                ],
            }
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatatalogueEntry]:
        from .config import GlobalConfig

        def excise_flavours(files: list[_CfCoreFile]):
            for flavour in Flavour:
                if any(
                    not f.get('exposeAsAlternative', False)
                    and any(
                        s['gameVersionTypeId']
                        == Flavour.to_flavour_keyed_enum(_CfCoreSortableGameVersionTypeId, flavour)
                        for s in f['sortableGameVersions']
                    )
                    for f in files
                ):
                    yield flavour

        def excise_folders(files: list[_CfCoreFile]):
            return uniq(frozenset(m['name'] for m in f['modules']) for f in files)

        api_key = cls._get_access_token(GlobalConfig())

        step = 20
        for index in count():
            url = (cls.mod_api_url / 'search').with_query(
                gameId='1',
                sortField=_CfCoreModsSearchSortField.name_,
                pageSize=step,
                index=index * step,
            )
            logger.debug(f'retrieving {url}')
            async with web_client.get(
                url, headers={'x-api-key': api_key}, raise_for_status=True
            ) as response:
                response_json: _CfCoreModsResponse = await response.json()

            items = response_json['data']
            if not items:
                break

            for item in items:
                yield BaseCatatalogueEntry.parse_obj(
                    {
                        'source': cls.source,
                        'id': item['id'],
                        'slug': item['slug'],
                        'name': item['name'],
                        'url': item['links']['websiteUrl'],
                        'game_flavours': excise_flavours(item['latestFiles']),
                        'download_count': item['downloadCount'],
                        'last_updated': item['dateReleased'],
                        'folders': excise_folders(item['latestFiles']),
                    }
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
    source = 'wowi'
    name = 'WoWInterface'
    strategies = frozenset({Strategy.default})
    changelog_format = ChangelogFormat.raw

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
    list_api_url = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    details_api_url = URL('https://api.mmoui.com/v3/game/WOW/filedetails/')

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
        async with self.manager.locks['load WoWI catalogue']:
            async with self.manager.web_client.get(
                self.list_api_url,
                {'hours': 1},
                label=f'Synchronising {self.name} catalogue',
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
        async with self.manager.web_client.get(
            self.details_api_url / f'{",".join(numeric_ids)}.json',
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

        return models.Pkg.parse_obj(
            {
                'source': self.source,
                'id': metadata['UID'],
                'slug': slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
                'name': metadata['UIName'],
                'description': metadata['UIDescription'],
                'url': metadata['UIFileInfoURL'],
                'download_url': metadata['UIDownload'],
                'date_published': metadata['UIDate'],
                'version': metadata['UIVersion'],
                'changelog_url': _format_data_changelog(metadata['UIChangeLog']),
                'options': {'strategy': defn.strategy},
            }
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatatalogueEntry]:
        flavours = set(Flavour)

        logger.debug(f'retrieving {cls.list_api_url}')
        async with web_client.get(cls.list_api_url, raise_for_status=True) as response:
            items: list[_WowiListApiItem] = await response.json()

        for item in items:
            yield BaseCatatalogueEntry.parse_obj(
                {
                    'source': cls.source,
                    'id': item['UID'],
                    'name': item['UIName'],
                    'url': item['UIFileInfoURL'],
                    'game_flavours': flavours,
                    'download_count': item['UIDownloadTotal'],
                    'last_updated': datetime.fromtimestamp(item['UIDate'] / 1000, timezone.utc),
                    'folders': [item['UIDir']],
                }
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
    source = 'tukui'
    name = 'Tukui'
    strategies = frozenset({Strategy.default})
    changelog_format = ChangelogFormat.html

    # There's also a ``/client-api.php`` endpoint which is apparently
    # used by the Tukui client itself to check for updates for the two retail
    # UIs only.  The response body appears to be identical to ``/api.php``
    api_url = URL('https://www.tukui.org/api.php')

    retail_ui_suites = {'elvui', 'tukui'}

    query_flavours = {
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
            async with self.manager.web_client.get(
                self.api_url.with_query({'ui': ui_slug}),
                {'minutes': 5},
                raise_for_status=True,
            ) as response:
                addon: _TukuiUi = await response.json()
            return [(str(addon['id']), addon), (ui_slug, addon)]

        async def fetch_addons(flavour: Flavour):
            async with self.manager.web_client.get(
                self.api_url.with_query({self.query_flavours[flavour]: 'all'}),
                {'minutes': 30},
                label=f'Synchronising {self.name} {flavour} catalogue',
                raise_for_status=True,
            ) as response:
                addons: list[_TukuiAddon] = await response.json()
            return [(str(a['id']), a) for a in addons]

        async with self.manager.locks['load Tukui catalogue']:
            addon_lists = await gather(
                [
                    *map(
                        fetch_ui,
                        self.retail_ui_suites
                        if self.manager.config.game_flavour is Flavour.retail
                        else [],
                    ),
                    fetch_addons(self.manager.config.game_flavour),
                ]
            )
            return {k: v for l in addon_lists for k, v in l}

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        addons = await self._synchronise()
        ids = (
            d.alias[:p] if d.alias not in self.retail_ui_suites and p != -1 else d.alias
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

        return models.Pkg.parse_obj(
            {
                'source': self.source,
                'id': str(metadata['id']),
                'slug': slug,
                'name': metadata['name'],
                'description': metadata['small_desc'],
                'url': metadata['web_url'],
                'download_url': metadata['url'],
                'date_published': datetime.fromisoformat(metadata['lastupdate']).replace(
                    tzinfo=timezone.utc
                ),
                'version': metadata['version'],
                'changelog_url': (
                    # The changelog URL is not versioned - adding fragment to allow caching
                    str(URL(metadata['changelog']).with_fragment(metadata['version']))
                    if metadata['id'] in {-1, -2}
                    # Regular add-ons don't have dedicated changelogs but rather
                    # link to the changelog tab on the add-on page
                    else _format_data_changelog(metadata['changelog'])
                ),
                'options': {'strategy': defn.strategy},
            }
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatatalogueEntry]:
        for flavours, query in [
            ({Flavour.retail}, {'ui': 'tukui'}),
            ({Flavour.retail}, {'ui': 'elvui'}),
            *(({f}, {q: 'all'}) for f, q in cls.query_flavours.items()),
        ]:
            url = cls.api_url.with_query(query)
            logger.debug(f'retrieving {url}')
            async with web_client.get(url, raise_for_status=True) as response:
                items: _TukuiUi | list[_TukuiAddon] = await response.json(
                    content_type=None  # text/html
                )

            for item in items if isinstance(items, list) else [items]:
                yield BaseCatatalogueEntry.parse_obj(
                    {
                        'source': cls.source,
                        'id': item['id'],
                        'name': item['name'],
                        'url': item['web_url'],
                        'game_flavours': flavours,
                        # Split Tukui and ElvUI downloads evenly between them.
                        # They both have the exact same number of downloads so
                        # I'm assuming they're being counted together.
                        # This should help with scoring other add-ons on the
                        # Tukui catalogue higher
                        'download_count': int(item['downloads'])
                        // (2 if item['id'] in {-1, -2} else 1),
                        'last_updated': datetime.fromisoformat(item['lastupdate']).replace(
                            tzinfo=timezone.utc
                        ),
                    }
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
    source = 'github'
    name = 'GitHub'
    strategies = frozenset({Strategy.default, Strategy.latest, Strategy.version})
    changelog_format = ChangelogFormat.markdown

    repos_api_url = URL('https://api.github.com/repos')

    generated_catalogue_csv_url = (
        'https://raw.githubusercontent.com/layday/github-wow-addon-catalogue/main/addons.csv'
    )

    @classmethod
    def get_alias_from_url(cls, url: URL) -> str | None:
        if url.host == 'github.com' and len(url.parts) > 2:
            return '/'.join(url.parts[1:3])

    async def resolve_one(self, defn: Defn, metadata: None) -> models.Pkg:
        github_get = self.manager.web_client.get
        github_token = self.manager.config.global_config.access_tokens.github
        if github_token is not None:
            github_get = partial(
                github_get, headers={'Authorization': f'token {github_token.get_secret_value()}'}
            )

        repo_url = self.repos_api_url / defn.alias

        async with github_get(repo_url, {'hours': 1}) as response:
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

        async with github_get(release_url, {'minutes': 5}) as response:
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
            raise R.PkgFileUnavailable('no `release.json` attached to release')

        async with self.manager.web_client.get(
            release_json['browser_download_url'], {'days': 1}, raise_for_status=True
        ) as response:
            packager_metadata: _PackagerReleaseJson = await response.json()

        releases = packager_metadata['releases']
        if not releases:
            raise R.PkgFileUnavailable('no files available for download')

        wanted_flavour = Flavour.to_flavour_keyed_enum(
            _PackagerReleaseJsonFlavor, self.manager.config.game_flavour
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
            raise R.PkgFileUnavailable(f'no files matching {self.manager.config.game_flavour}')

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

        return models.Pkg.parse_obj(
            {
                'source': self.source,
                'id': project_metadata['full_name'],
                'slug': project_metadata['full_name'].lower(),
                'name': project_metadata['name'],
                'description': project_metadata['description'] or '',
                'url': project_metadata['html_url'],
                'download_url': matching_asset['browser_download_url'],
                'date_published': release_metadata['published_at'],
                'version': release_metadata['tag_name'],
                'changelog_url': _format_data_changelog(release_metadata['body']),
                'options': {'strategy': defn.strategy},
            }
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatatalogueEntry]:
        import csv
        import io

        logger.debug(f'retrieving {cls.generated_catalogue_csv_url}')
        async with web_client.get(
            cls.generated_catalogue_csv_url, raise_for_status=True
        ) as response:
            catalogue_csv = await response.text()

        for entry in csv.DictReader(io.StringIO(catalogue_csv)):
            if entry['has_release_json'] != 'True':
                continue

            yield BaseCatatalogueEntry.parse_obj(
                {
                    'source': cls.source,
                    'id': entry['full_name'],
                    'slug': entry['full_name'].lower(),
                    'name': entry['name'],
                    'url': entry['url'],
                    'game_flavours': {
                        Flavour.from_flavour_keyed_enum(_PackagerReleaseJsonFlavor(f))
                        for f in entry['flavors'].split(',')
                    },
                    'download_count': 1,
                    'last_updated': datetime.fromisoformat(entry['last_updated']),
                    'same_as': [
                        {'source': i, 'id': v}
                        for i in ['curse', 'wowi']
                        for v in (entry[f'{i}_id'],)
                        if v
                    ],
                }
            )


class InstawowResolver(BaseResolver):
    source = 'instawow'
    name = 'instawow'
    strategies = frozenset({Strategy.default})
    changelog_format = ChangelogFormat.markdown

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

        builder = WaCompanionBuilder(self.manager)
        if source_id == '1':
            await builder.build()

        return models.Pkg.parse_obj(
            {
                'source': self.source,
                'id': source_id,
                'slug': slug,
                'name': 'WeakAuras Companion',
                'description': 'A WeakAuras Companion clone.',
                'url': 'https://github.com/layday/instawow',
                'download_url': builder.addon_zip_path.as_uri(),
                'date_published': datetime.now(timezone.utc),
                'version': (await builder.get_checksum())[:7],
                'changelog_url': builder.changelog_path.as_uri(),
                'options': {'strategy': defn.strategy},
            }
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[BaseCatatalogueEntry]:
        yield BaseCatatalogueEntry.parse_obj(
            {
                'source': cls.source,
                'id': '1',
                'slug': 'weakauras-companion-autoupdate',
                'name': 'WeakAuras Companion',
                'url': 'https://github.com/layday/instawow',
                'game_flavours': set(Flavour),
                'download_count': 1,
                'last_updated': datetime.now(timezone.utc),
                'folders': [
                    {'WeakAurasCompanion'},
                ],
            }
        )
