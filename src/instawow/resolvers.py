from __future__ import annotations

from collections.abc import AsyncIterator, Sequence, Set
from datetime import datetime, timezone
from enum import Enum
from itertools import chain, takewhile
import re
import typing
from typing import Any, ClassVar

from loguru import logger
from pydantic import BaseModel
from pydantic.datetime_parse import parse_datetime
from typing_extensions import Literal, TypedDict
from yarl import URL

from . import _deferred_types, manager, models, results as R
from .config import Flavour
from .utils import bucketise, cached_property, gather, uniq


class Strategy(str, Enum):
    default = 'default'
    latest = 'latest'
    curse_latest_beta = 'curse_latest_beta'
    curse_latest_alpha = 'curse_latest_alpha'
    any_flavour = 'any_flavour'
    version = 'version'


class ChangelogFormat(str, Enum):
    html = 'html'
    markdown = 'markdown'
    bbcode = 'bbcode'
    raw = 'raw'


class Defn(
    BaseModel,
    frozen=True,
):
    source: str
    alias: str
    id: typing.Optional[str] = None
    strategy: Strategy = Strategy.default
    version: typing.Optional[str] = None

    @classmethod
    def from_pkg(cls, pkg: models.Pkg | PkgModel) -> Defn:
        return cls(
            source=pkg.source,
            alias=pkg.slug,
            id=pkg.id,
            strategy=pkg.options.strategy,
            version=pkg.version,
        )

    def __init__(self, source: str, alias: str, **kwargs: object) -> None:
        super().__init__(source=source, alias=alias, **kwargs)

    def with_(self, **kwargs: Any) -> Defn:
        return self.__class__(**{**self.__dict__, **kwargs})

    def with_strategy(self, strategy: Strategy) -> Defn:
        return self.with_(strategy=strategy)

    def with_version(self, version: str) -> Defn:
        return self.with_(strategy=Strategy.version, version=version)

    def to_uri(self) -> str:
        return f'{self.source}:{self.alias}'


def normalise_names(replace_delim: str):
    import string

    trans_table = str.maketrans(dict.fromkeys(string.punctuation, ' '))

    def normalise(value: str):
        return replace_delim.join(value.casefold().translate(trans_table).split())

    return normalise


_slugify = normalise_names('-')


def _format_data_changelog(changelog: str = '') -> str:
    import urllib.parse

    return f'data:,{urllib.parse.quote(changelog)}'


class _CatalogueBaseEntry(TypedDict):
    source: str
    id: str
    slug: str
    name: str
    game_flavours: Set[Flavour]
    folders: Sequence[Sequence[str]]
    download_count: int
    last_updated: datetime | int | str


class CatalogueEntry(BaseModel):
    source: str
    id: str
    slug: str
    name: str
    game_flavours: typing.Set[Flavour]
    folders: typing.List[typing.Set[str]]
    download_count: int
    last_updated: datetime
    derived_download_score: float


class Catalogue(
    BaseModel,
    json_encoders={set: sorted},
    keep_untouched=(cached_property,),
):
    __root__: typing.List[CatalogueEntry]

    @classmethod
    async def collate(cls, age_cutoff: datetime | None) -> Catalogue:
        async with manager.init_web_client() as web_client:
            items = [a for r in manager.Manager.RESOLVERS async for a in r.catalogue(web_client)]

        most_downloads_per_source = {
            s: max(e['download_count'] for e in i)
            for s, i in bucketise(items, key=lambda v: v['source']).items()
        }
        entries = (
            CatalogueEntry(
                **i,
                derived_download_score=i['download_count']
                / most_downloads_per_source[i['source']],
            )
            for i in items
        )
        if age_cutoff:
            entries = (e for e in entries if e.last_updated >= age_cutoff)
        catalogue = cls.parse_obj(list(entries))
        return catalogue

    @cached_property
    def curse_slugs(self) -> dict[str, str]:
        return {a.slug: a.id for a in self.__root__ if a.source == 'curse'}


class _PkgModel_PkgFolder(
    BaseModel,
    orm_mode=True,
):
    name: str


class _PkgModel_PkgOptions(
    BaseModel,
    orm_mode=True,
):
    strategy: Strategy


class _PkgModel_PkgDep(
    BaseModel,
    orm_mode=True,
):
    id: str


class _PkgModel_PkgVersion(
    BaseModel,
    orm_mode=True,
):
    version: str
    install_time: datetime


class PkgModel(
    BaseModel,
    orm_mode=True,
):
    source: str
    id: str
    slug: str
    name: str
    description: str
    url: str
    download_url: str
    date_published: datetime
    version: str
    changelog_url: str
    folders: typing.List[_PkgModel_PkgFolder]
    options: _PkgModel_PkgOptions
    deps: typing.List[_PkgModel_PkgDep]
    logged_versions: typing.List[_PkgModel_PkgVersion]


class MultiPkgModel(BaseModel):
    __root__: typing.List[PkgModel]


class Resolver:
    source: ClassVar[str]
    name: ClassVar[str]
    strategies: ClassVar[Set[Strategy]]
    changelog_format: ClassVar[ChangelogFormat]

    def __init__(self, manager: manager.Manager) -> None:
        self.manager = manager

    @property
    def supports_rollback(self) -> bool:
        "Whether the resolver supports rollback operations."
        return Strategy.version in self.strategies

    @staticmethod
    def get_alias_from_url(value: str) -> str | None:
        "Attempt to extract a definition name from a given URL."

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        "Resolve add-on definitions into packages."
        results = await gather(
            (self.resolve_one(d, None) for d in defns), manager.capture_manager_exc_async
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: Any) -> models.Pkg:
        "Resolve an individual definition into a package."
        raise NotImplementedError

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[_CatalogueBaseEntry]:
        "Yield add-ons from source for cataloguing."
        return
        yield


# Only documenting the fields we're actually using -
# the API response is absolutely massive
class CurseAddon_FileDependency(TypedDict):
    id: int  # Unique dependency ID
    addonId: int  # The ID of the add-on we're depending on
    # The type of dependency.  One of:
    #   1 = embedded library
    #   2 = optional dependency
    #   3 = required dependency (this is the one we're after)
    #   4 = tool
    #   5 = incompatible
    #   6 = include (wat)
    type: int
    fileId: int  # The ID of the parent file which has this as a dependency


class CurseAddon_FileModules(TypedDict):
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
    type: int


class CurseAddon_File(TypedDict):
    id: int  # Unique file ID
    displayName: str  # Tends to be the version
    downloadUrl: str
    fileDate: str  # Upload datetime in ISO, e.g. '2020-02-02T12:12:12Z'
    releaseType: int  # 1 = stable; 2 = beta; 3 = alpha
    dependencies: list[CurseAddon_FileDependency]
    modules: list[CurseAddon_FileModules]
    exposeAsAlternative: bool | None
    gameVersion: list[str]  # e.g. '8.3.0'
    gameVersionFlavor: Literal['wow_classic', 'wow_retail'] | None


class CurseAddon(TypedDict):
    id: int
    name: str  # User-facing add-on name
    websiteUrl: str  # e.g. 'https://www.curseforge.com/wow/addons/molinari'
    summary: str  # One-line description of the add-on
    downloadCount: int  # Total number of downloads
    latestFiles: list[CurseAddon_File]
    slug: str  # URL slug; 'molinari' in 'https://www.curseforge.com/wow/addons/molinari'
    dateReleased: str  # ISO datetime of latest release


class CurseResolver(Resolver):
    source = 'curse'
    name = 'CurseForge'
    strategies = frozenset(
        {
            Strategy.default,
            Strategy.latest,
            Strategy.curse_latest_beta,
            Strategy.curse_latest_alpha,
            Strategy.any_flavour,
            Strategy.version,
        }
    )
    changelog_format = ChangelogFormat.html

    # Reference: https://twitchappapi.docs.apiary.io/
    addon_api_url = URL('https://addons-ecs.forgesvc.net/api/v2/addon')

    @staticmethod
    def get_alias_from_url(value: str) -> str | None:
        url = URL(value)
        if url.host == 'www.wowace.com' and len(url.parts) > 2 and url.parts[1] == 'projects':
            return url.parts[2].lower()
        elif (
            url.host == 'www.curseforge.com'
            and len(url.parts) > 3
            and url.parts[1:3] == ('wow', 'addons')
        ):
            return url.parts[3].lower()

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        from aiohttp import ClientResponseError

        catalogue = await self.manager.synchronise()

        defns_to_ids = {d: d.id or catalogue.curse_slugs.get(d.alias) or d.alias for d in defns}
        numeric_ids = uniq(i for i in defns_to_ids.values() if i.isdigit())
        try:
            json_response: list[CurseAddon] = await manager.cache_response(
                self.manager,
                self.addon_api_url,
                {'minutes': 5},
                request_extra={'method': 'POST', 'json': numeric_ids},
            )
        except ClientResponseError as error:
            if error.status != 404:
                raise
            json_response = []

        api_results = {str(r['id']): r for r in json_response}
        results = await gather(
            (self.resolve_one(d, api_results.get(i)) for d, i in defns_to_ids.items()),
            manager.capture_manager_exc_async,
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: CurseAddon | None) -> models.Pkg:
        if metadata is None:
            raise R.PkgNonexistent

        if defn.strategy not in self.strategies:
            raise R.PkgStrategyUnsupported(defn.strategy)

        if defn.strategy is Strategy.version:

            files = await manager.cache_response(
                self.manager,
                self.addon_api_url / str(metadata['id']) / 'files',
                {'hours': 1},
                label=f'Fetching metadata from {self.name}',
            )

            def is_version_match(f: CurseAddon_File):
                return defn.version == f['displayName']

            is_match = is_version_match
        else:

            files = metadata['latestFiles']

            def is_not_libless(f: CurseAddon_File):
                # There's also an 'isAlternate' field that's missing from some
                # 50 lib-less files from c. 2008.  'exposeAsAlternative' is
                # absent from the /file endpoint
                return not f['exposeAsAlternative']

            if defn.strategy is Strategy.any_flavour:

                def supports_any_game_version(f: CurseAddon_File):
                    return True

                supports_game_version = supports_any_game_version
            else:

                # Files can have multiple ``gameVersion``s but ``gameVersionFlavor``
                # is a scalar....but also ``gameVersion`` might not be populated -
                # we fall back on it only if ``gameVersionFlavor`` does not match
                if self.manager.config.game_flavour is Flavour.retail:

                    def supports_retail(f: CurseAddon_File):
                        return f['gameVersionFlavor'] == 'wow_retail' or any(
                            not v.startswith(('1.13', '2.5')) for v in f['gameVersion']
                        )

                    supports_game_version = supports_retail
                elif self.manager.config.game_flavour is Flavour.vanilla_classic:

                    def supports_vanilla_classic(f: CurseAddon_File):
                        return f['gameVersionFlavor'] == 'wow_classic' or any(
                            v.startswith('1.13') for v in f['gameVersion']
                        )

                    supports_game_version = supports_vanilla_classic
                elif self.manager.config.game_flavour is Flavour.burning_crusade_classic:

                    def supports_burning_crusade(f: CurseAddon_File):
                        return f['gameVersionFlavor'] == 'wow_burning_crusade' or any(
                            v.startswith('2.5') for v in f['gameVersion']
                        )

                    supports_game_version = supports_burning_crusade

            if defn.strategy is Strategy.latest:

                def has_latest_release_type(f: CurseAddon_File):
                    return True

                has_release_type = has_latest_release_type
            elif defn.strategy is Strategy.curse_latest_beta:

                def has_curse_latest_beta_release_type(f: CurseAddon_File):
                    return f['releaseType'] == 2

                has_release_type = has_curse_latest_beta_release_type
            elif defn.strategy is Strategy.curse_latest_alpha:

                def has_curse_latest_alpha_release_type(f: CurseAddon_File):
                    return f['releaseType'] == 3

                has_release_type = has_curse_latest_alpha_release_type
            else:

                def has_default_release_type(f: CurseAddon_File):
                    return f['releaseType'] == 1

                has_release_type = has_default_release_type

            def is_default_match(f: CurseAddon_File):
                return is_not_libless(f) and supports_game_version(f) and has_release_type(f)

            is_match = is_default_match

        if not files:
            raise R.PkgFileUnavailable('no files available for download')

        try:
            file = max(
                filter(is_match, files),
                # The ``id`` is just a counter so we don't have to go digging around dates
                key=lambda f: f['id'],
            )
        except ValueError:
            raise R.PkgFileUnavailable(
                f'no files match {self.manager.config.game_flavour} '
                f'using {defn.strategy} strategy'
            )

        addon_id = str(metadata['id'])
        file_id = str(file['id'])

        return models.Pkg(
            source=self.source,
            id=addon_id,
            slug=metadata['slug'],
            name=metadata['name'],
            description=metadata['summary'],
            url=metadata['websiteUrl'],
            download_url=file['downloadUrl'],
            date_published=parse_datetime(file['fileDate']),
            version=file['displayName'],
            changelog_url=str(self.addon_api_url / addon_id / 'file' / file_id / 'changelog'),
            options=models.PkgOptions(strategy=defn.strategy),
            deps=[
                models.PkgDep(id=str(d['addonId'])) for d in file['dependencies'] if d['type'] == 3
            ],
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[_CatalogueBaseEntry]:
        def excise_flavours(files: list[CurseAddon_File]):
            if any(f['gameVersionFlavor'] == 'wow_retail' for f in files) or any(
                not v.startswith(('1.13', '2.5')) for f in files for v in f['gameVersion']
            ):
                yield Flavour.retail
            if any(f['gameVersionFlavor'] == 'wow_classic' for f in files) or any(
                v.startswith('1.13') for f in files for v in f['gameVersion']
            ):
                yield Flavour.vanilla_classic
            if any(f['gameVersionFlavor'] == 'wow_burning_crusade' for f in files) or any(
                v.startswith('2.5') for f in files for v in f['gameVersion']
            ):
                yield Flavour.burning_crusade_classic

        step = 50
        sort_order = '3'  # Alphabetical
        for index in range(0, 10001 - step, step):
            async with web_client.get(
                (cls.addon_api_url / 'search').with_query(
                    gameId='1', sort=sort_order, pageSize=step, index=index
                )
            ) as response:
                json_response: list[CurseAddon] = await response.json()

            if not json_response:
                break

            for item in json_response:
                yield _CatalogueBaseEntry(
                    source=cls.source,
                    id=str(item['id']),
                    slug=item['slug'],
                    name=item['name'],
                    game_flavours=set(excise_flavours(item['latestFiles'])),
                    folders=uniq(
                        tuple(m['foldername'] for m in f['modules'])
                        for f in item['latestFiles']
                        if not f['exposeAsAlternative']
                    ),
                    download_count=item['downloadCount'],
                    last_updated=item['dateReleased'],
                )


class WowiCommonTerms(TypedDict):
    UID: str  # Unique add-on ID
    UICATID: str  # ID of category add-on is placed in
    UIVersion: str  # Add-on version
    UIDate: int  # Upload date expressed as unix epoch
    UIName: str  # User-facing add-on name
    UIAuthorName: str


class WowiListApiItem_CompatibilityEntry(TypedDict):
    version: str  # Game version, e.g. '8.3.0'
    name: str  # Xpac or patch name, e.g. "Visions of N'Zoth" for 8.3.0


class WowiListApiItem(WowiCommonTerms):
    UIFileInfoURL: str  # Add-on page on WoWI
    UIDownloadTotal: str  # Total number of downloads
    UIDownloadMonthly: str  # Number of downloads in the last month and not 'monthly'
    UIFavoriteTotal: str
    UICompatibility: list[WowiListApiItem_CompatibilityEntry] | None  # ``null`` if would be empty
    UIDir: list[str]  # Names of folders contained in archive
    UIIMG_Thumbs: list[str] | None  # Thumbnail URLs; ``null`` if would be empty
    UIIMGs: list[str] | None  # Full-size image URLs; ``null`` if would be empty
    # There are only two add-ons on the entire list with siblings
    # (they refer to each other). I don't know if this was meant to capture
    # dependencies (probably not) but it's so underused as to be worthless.
    # ``null`` if would be empty
    UISiblings: list[str] | None
    UIDonationLink: str | None  # Absent from the first item on the list (!)


class WowiDetailsApiItem(WowiCommonTerms):
    UIMD5: str | None  # Archive hash, ``null` when UI is pending
    UIFileName: str  # The actual filename, e.g. 'foo.zip'
    UIDownload: str  # Download URL
    UIPending: Literal['0', '1']  # Set to '1' if the file is awaiting approval
    UIDescription: str  # Long description with BB Code and all
    UIChangeLog: str  # This can also contain BB Code
    UIHitCount: str  # Same as UIDownloadTotal
    UIHitCountMonthly: str  # Same as UIDownloadMonthly


class WowiCombinedItem(WowiListApiItem, WowiDetailsApiItem):
    pass


class WowiResolver(Resolver):
    source = 'wowi'
    name = 'WoWInterface'
    strategies = frozenset({Strategy.default})
    changelog_format = ChangelogFormat.bbcode

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

    @staticmethod
    def get_alias_from_url(value: str) -> str | None:
        url = URL(value)
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
                return match and match.group('id')

    async def _synchronise(self) -> dict[str, WowiListApiItem]:
        async with self.manager.locks['load WoWI catalogue']:
            list_api_items = await manager.cache_response(
                self.manager,
                self.list_api_url,
                {'hours': 1},
                label=f'Synchronising {self.name} catalogue',
            )
            return {i['UID']: i for i in list_api_items}

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        from aiohttp import ClientResponseError

        list_api_items = await self._synchronise()

        defns_to_ids = {d: ''.join(takewhile(str.isdigit, d.alias)) for d in defns}
        numeric_ids = set(filter(None, defns_to_ids.values()))
        try:
            details_api_items: list[WowiDetailsApiItem] = await manager.cache_response(
                self.manager,
                self.details_api_url / f'{",".join(numeric_ids)}.json',
                {'minutes': 5},
            )
        except ClientResponseError as error:
            if error.status != 404:
                raise
            details_api_items = []

        combined_items: dict[str, Any] = {
            i['UID']: {**list_api_items[i['UID']], **i} for i in details_api_items
        }
        results = await gather(
            (self.resolve_one(d, combined_items.get(i)) for d, i in defns_to_ids.items()),
            manager.capture_manager_exc_async,
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: WowiCombinedItem | None) -> models.Pkg:
        if metadata is None:
            raise R.PkgNonexistent

        if defn.strategy not in self.strategies:
            raise R.PkgStrategyUnsupported(defn.strategy)

        return models.Pkg(
            source=self.source,
            id=metadata['UID'],
            slug=_slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
            name=metadata['UIName'],
            description=metadata['UIDescription'],
            url=metadata['UIFileInfoURL'],
            download_url=metadata['UIDownload'],
            date_published=parse_datetime(metadata['UIDate']),
            version=metadata['UIVersion'],
            changelog_url=_format_data_changelog(metadata['UIChangeLog']),
            options=models.PkgOptions(strategy=defn.strategy),
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[_CatalogueBaseEntry]:
        async with web_client.get(cls.list_api_url) as response:
            list_api_items: list[WowiListApiItem] = await response.json()

        flavours = set(Flavour)
        for list_item in list_api_items:
            yield _CatalogueBaseEntry(
                source=cls.source,
                id=list_item['UID'],
                name=list_item['UIName'],
                slug='',
                folders=[list_item['UIDir']],
                game_flavours=flavours,
                download_count=int(list_item['UIDownloadTotal']),
                last_updated=list_item['UIDate'],
            )


class TukuiUi(TypedDict):
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


class TukuiAddon(TypedDict):
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


class TukuiResolver(Resolver):
    source = 'tukui'
    name = 'Tukui'
    strategies = frozenset({Strategy.default})
    changelog_format = ChangelogFormat.html

    # There's also a ``/client-api.php`` endpoint which is apparently
    # used by the Tukui client itself to check for updates for the two retail
    # UIs only.  The response body appears to be identical to ``/api.php``
    api_url = URL('https://www.tukui.org/api.php')

    @staticmethod
    def get_alias_from_url(value: str) -> str | None:
        url = URL(value)
        if url.host == 'www.tukui.org':
            if url.path in {'/addons.php', '/classic-addons.php', '/classic-tbc-addons.php'}:
                return url.query.get('id')
            elif url.path == '/download.php':
                return url.query.get('ui')

    async def _synchronise(self) -> dict[str, TukuiAddon | TukuiUi]:
        async def fetch_ui(ui_slug: str):
            addon: TukuiUi = await manager.cache_response(
                self.manager,
                self.api_url.with_query({'ui': ui_slug}),
                {'minutes': 5},
            )
            return [(str(addon['id']), addon), (ui_slug, addon)]

        async def fetch_addons(flavour: Flavour):
            if flavour is Flavour.retail:
                query = 'addons'
            elif flavour is Flavour.vanilla_classic:
                query = 'classic-addons'
            else:  # Flavour.burning_crusade_classic
                query = 'classic-tbc-addons'

            addons: list[TukuiAddon] = await manager.cache_response(
                self.manager,
                self.api_url.with_query({query: 'all'}),
                {'minutes': 30},
                label=f'Synchronising {self.name} {flavour} catalogue',
            )
            return [(str(a['id']), a) for a in addons]

        async with self.manager.locks['load Tukui catalogue']:
            requests = await gather(
                (
                    (fetch_ui('tukui'), fetch_ui('elvui'))
                    if self.manager.config.game_flavour is Flavour.retail
                    else ()
                )
                + (fetch_addons(self.manager.config.game_flavour),)
            )
            return {k: v for l in requests for k, v in l}

    async def resolve(
        self, defns: Sequence[Defn]
    ) -> dict[Defn, models.Pkg | R.ManagerError | R.InternalError]:
        addons = await self._synchronise()
        ids = (d.alias[: p if p != -1 else None] for d in defns for p in (d.alias.find('-', 1),))
        results = await gather(
            (self.resolve_one(d, addons.get(i)) for d, i in zip(defns, ids)),
            manager.capture_manager_exc_async,
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: TukuiAddon | TukuiUi | None) -> models.Pkg:
        if metadata is None:
            raise R.PkgNonexistent

        if defn.strategy not in self.strategies:
            raise R.PkgStrategyUnsupported(defn.strategy)

        if metadata['id'] == -1:
            slug = 'tukui'
        elif metadata['id'] == -2:
            slug = 'elvui'
        else:
            slug = _slugify(f'{metadata["id"]} {metadata["name"]}')

        return models.Pkg(
            source=self.source,
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
    ) -> AsyncIterator[_CatalogueBaseEntry]:
        async def fetch_ui(ui_slug: str) -> tuple[set[Flavour], list[TukuiUi]]:
            async with web_client.get(cls.api_url.with_query({'ui': ui_slug})) as response:
                return ({Flavour.retail}, [await response.json(content_type=None)])  # text/html

        async def fetch_addons(flavour: Flavour) -> tuple[set[Flavour], list[TukuiAddon]]:
            if flavour is Flavour.retail:
                query = 'addons'
            elif flavour is Flavour.vanilla_classic:
                query = 'classic-addons'
            else:  # Flavour.burning_crusade_classic
                query = 'classic-tbc-addons'
            async with web_client.get(cls.api_url.with_query({query: 'all'})) as response:
                return ({flavour}, await response.json(content_type=None))  # text/html

        for flavours, items in await gather(
            [
                fetch_ui('tukui'),
                fetch_ui('elvui'),
                fetch_addons(Flavour.retail),
                fetch_addons(Flavour.vanilla_classic),
                fetch_addons(Flavour.burning_crusade_classic),
            ]
        ):
            for item in items:
                yield _CatalogueBaseEntry(
                    source=cls.source,
                    id=str(item['id']),
                    slug='',
                    name=item['name'],
                    folders=[],
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
class GithubRepo(TypedDict):
    name: str  # the repo in user-or-org/repo
    full_name: str  # user-or-org/repo
    description: str
    html_url: str


class GithubRelease_Asset(TypedDict):
    name: str  # filename
    content_type: str  # mime type
    state: Literal['starter', 'uploaded']
    browser_download_url: str


class GithubRelease(TypedDict):
    tag_name: str  # Hopefully the version
    published_at: str  # ISO datetime
    assets: list[GithubRelease_Asset]
    body: str


class PackagerReleaseJson(TypedDict):
    releases: list[PackagerReleaseJson_Release]


class PackagerReleaseJson_Release(TypedDict):
    filename: str
    nolib: bool
    metadata: list[PackagerReleaseJson_Release_Metadata]


class PackagerReleaseJson_Release_Metadata(TypedDict):
    flavor: Literal['mainline', 'classic', 'bcc']
    interface: int


class GithubResolver(Resolver):
    source = 'github'
    name = 'GitHub'
    strategies = frozenset({Strategy.default, Strategy.latest, Strategy.version})
    changelog_format = ChangelogFormat.markdown

    repos_api_url = URL('https://api.github.com/repos')

    @staticmethod
    def get_alias_from_url(value: str) -> str | None:
        url = URL(value)
        if url.host == 'github.com' and len(url.parts) > 2:
            return '/'.join(url.parts[1:3])

    async def resolve_one(self, defn: Defn, metadata: None) -> models.Pkg:
        from aiohttp import ClientResponseError

        if defn.strategy not in self.strategies:
            raise R.PkgStrategyUnsupported(defn.strategy)

        repo_url = self.repos_api_url / defn.alias

        try:
            project_metadata: GithubRepo = await manager.cache_response(
                self.manager, repo_url, {'hours': 1}
            )
        except ClientResponseError as error:
            if error.status == 404:
                raise R.PkgNonexistent
            raise

        if defn.strategy is Strategy.version:
            assert defn.version
            release_url = repo_url / 'releases/tags' / defn.version
        elif defn.strategy is Strategy.latest:
            release_url = (repo_url / 'releases').with_query(per_page='1')
        else:
            # The latest release is the most recent non-prerelease,
            # non-draft release, sorted by the ``created_at`` attribute.
            # See: https://docs.github.com/en/free-pro-team@latest/rest/reference/repos#get-the-latest-release
            release_url = repo_url / 'releases/latest'

        async with self.manager.web_client.get(release_url) as response:
            if response.status == 404:
                raise R.PkgFileUnavailable('release not found')

            response_json = await response.json()
            if defn.strategy is Strategy.latest:
                (response_json,) = response_json
            release_metadata: GithubRelease = response_json

        assets = release_metadata['assets']

        try:
            release_json = next(
                a for a in assets if a['name'] == 'release.json' and a['state'] == 'uploaded'
            )
        except StopIteration:
            logger.info(f'no release.json found for {defn}; inspecting assets')

            def is_valid_asset(asset: GithubRelease_Asset):
                return (
                    # There is something of a convention that Classic archives
                    # end in '-classic' and lib-less archives end in '-nolib'.
                    # Archives produced by packager follow this convention
                    not asset['name'].endswith(('-nolib.zip', '-nolib-classic.zip'))
                    and asset['content_type']
                    in {'application/zip', 'application/x-zip-compressed'}
                    # A failed upload has a state value of 'starter'
                    and asset['state'] == 'uploaded'
                )

            try:
                matching_asset = next(
                    chain(
                        (
                            a
                            for a in assets
                            if is_valid_asset(a)
                            and a['name'].endswith('-classic.zip')
                            is (self.manager.config.game_flavour is Flavour.vanilla_classic)
                        ),
                        filter(is_valid_asset, assets),
                    )
                )
            except StopIteration:
                raise R.PkgFileUnavailable

        else:
            logger.info(f'reading metadata for {defn} from release.json')

            packager_metadata: PackagerReleaseJson = await manager.cache_response(
                self.manager, release_json['browser_download_url'], {'days': 1}
            )
            game_flavour: Flavour = self.manager.config.game_flavour
            if game_flavour is Flavour.retail:
                release_json_flavour = 'mainline'
            elif game_flavour is Flavour.vanilla_classic:
                release_json_flavour = 'classic'
            else:  # Flavour.burning_crusade_classic
                release_json_flavour = 'bcc'

            try:
                matching_release = next(
                    r
                    for r in packager_metadata['releases']
                    if r['nolib'] is False
                    and any(m['flavor'] == release_json_flavour for m in r['metadata'])
                )
                matching_asset = next(
                    a
                    for a in assets
                    if a['name'] == matching_release['filename'] and a['state'] == 'uploaded'
                )
            except StopIteration:
                raise R.PkgFileUnavailable

        return models.Pkg(
            source=self.source,
            id=project_metadata['full_name'],
            slug=project_metadata['full_name'].lower(),
            name=project_metadata['name'],
            description=project_metadata['description'],
            url=project_metadata['html_url'],
            download_url=matching_asset['browser_download_url'],
            date_published=parse_datetime(release_metadata['published_at']),
            version=release_metadata['tag_name'],
            changelog_url=_format_data_changelog(release_metadata['body']),
            options=models.PkgOptions(strategy=defn.strategy),
        )


class InstawowResolver(Resolver):
    source = 'instawow'
    name = 'instawow'
    strategies = frozenset({Strategy.default})
    changelog_format = ChangelogFormat.markdown

    _addons = {
        ('0', 'weakauras-companion'),
        ('1', 'weakauras-companion-autoupdate'),
    }

    async def resolve_one(self, defn: Defn, metadata: None) -> models.Pkg:
        if defn.strategy not in self.strategies:
            raise R.PkgStrategyUnsupported(defn.strategy)

        try:
            source_id, slug = next(p for p in self._addons if defn.alias in p)
        except StopIteration:
            raise R.PkgNonexistent

        from .wa_updater import BuilderConfig, WaCompanionBuilder

        builder = WaCompanionBuilder(self.manager, BuilderConfig())
        if source_id == '1':
            await builder.build()

        return models.Pkg(
            source=self.source,
            id=source_id,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            download_url=builder.addon_zip_path.as_uri(),
            date_published=datetime.now(timezone.utc),
            version=(await builder.get_checksum())[:7],
            changelog_url=builder.changelog_path.as_uri(),
            options=models.PkgOptions(strategy=defn.strategy),
        )

    @classmethod
    async def catalogue(
        cls, web_client: _deferred_types.aiohttp.ClientSession
    ) -> AsyncIterator[_CatalogueBaseEntry]:
        yield _CatalogueBaseEntry(
            source=cls.source,
            id='1',
            slug='weakauras-companion-autoupdate',
            name='WeakAuras Companion',
            folders=[
                ['WeakAurasCompanion'],
            ],
            game_flavours=set(Flavour),
            download_count=1,
            last_updated=datetime.now(timezone.utc),
        )
