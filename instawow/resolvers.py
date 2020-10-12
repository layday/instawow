from __future__ import annotations

from datetime import datetime, timezone
import enum
from itertools import chain, count, takewhile
import re
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    Callable,
    ClassVar,
    Dict,
    FrozenSet,
    List,
    Optional as O,
    Sequence,
    Set,
    Union,
    cast,
)

from pydantic import BaseModel
from pydantic.datetime_parse import parse_datetime
from typing_extensions import Literal, TypedDict
from yarl import URL

from . import exceptions as E, models as m
from .utils import bucketise, cached_property, gather, run_in_thread as t, uniq

if TYPE_CHECKING:
    import aiohttp

    from .manager import Manager as ManagerT


class Strategy(enum.Enum):
    default = 'default'
    latest = 'latest'
    curse_latest_beta = 'curse_latest_beta'
    curse_latest_alpha = 'curse_latest_alpha'
    any_flavour = 'any_flavour'
    version = 'version'


class _HashableModel(BaseModel):
    class Config:
        allow_mutation = False

    def __eq__(self, other: object) -> bool:
        return self.__dict__ == (other.__dict__ if isinstance(other, self.__class__) else other)

    def __hash__(self) -> int:
        return hash(tuple(self.__dict__.items()))


class Defn(_HashableModel):
    source: str
    alias: str
    id: O[str] = None
    strategy: Strategy = Strategy.default
    version: O[str] = None

    @classmethod
    def from_pkg(cls, pkg: Union[m.Pkg, PkgModel]) -> Defn:
        return cls(
            source=pkg.source,
            id=pkg.id,
            alias=pkg.slug,
            strategy=pkg.options.strategy,
            version=pkg.version,
        )

    def __init__(self, source: str, alias: str, **kwargs: Any) -> None:
        super().__init__(source=source, alias=alias, **kwargs)

    def with_(self, **kwargs: Any) -> Defn:
        return self.__class__(**{**self.__dict__, **kwargs})

    def with_strategy(self, strategy: Strategy) -> Defn:
        return self.with_(strategy=strategy)

    def with_version(self, version: str) -> Defn:
        return self.with_(strategy=Strategy.version, version=version)

    def __str__(self) -> str:
        return f'{self.source}:{self.alias}'


def normalise_names(replace_delim: str = ' '):
    import string

    trans_table = str.maketrans(dict.fromkeys(string.punctuation, ' '))

    def normalise(value: str):
        return replace_delim.join(value.casefold().translate(trans_table).split())

    return normalise


_slugify = normalise_names('-')


class _CatalogueEntryDefaultFields(TypedDict):
    source: str
    id: str
    slug: str
    name: str
    game_compatibility: Set[Literal['retail', 'classic']]
    folders: Sequence[Sequence[str]]
    download_count: int
    last_updated: Any


class _CatalogueEntry(BaseModel):
    source: str
    id: str
    slug: str
    name: str
    game_compatibility: Set[Literal['retail', 'classic']]
    folders: List[FrozenSet[str]]
    download_count: int
    last_updated: datetime
    normalised_name: str
    derived_download_score: float


class Catalogue(BaseModel):
    __root__: List[_CatalogueEntry]

    class Config:
        json_encoders: Dict[type, Callable[..., Any]] = {
            set: sorted,
            frozenset: sorted,
        }
        keep_untouched: Sequence[Any] = (cached_property,)

    @classmethod
    async def collate(cls, age_cutoff: O[datetime]) -> Catalogue:
        from .manager import init_web_client

        resolvers = (CurseResolver, WowiResolver, TukuiResolver, InstawowResolver)

        async with init_web_client() as web_client:
            items = [a for r in resolvers async for a in r.collect_items(web_client)]

        normalise = normalise_names()
        most_downloads_per_source = {
            s: max(e['download_count'] for e in i)
            for s, i in bucketise(items, key=lambda v: v['source']).items()
        }
        entries = (
            _CatalogueEntry(
                **i,
                normalised_name=normalise(i['name']),
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
    def curse_slugs(self) -> Dict[str, str]:
        return {a.slug: a.id for a in self.__root__ if a.source == 'curse'}


class _OrmModel(BaseModel):
    class Config:
        allow_mutation = False
        orm_mode = True


class _PkgModel_PkgFolder(_OrmModel):
    name: str


class _PkgModel_PkgOptions(_OrmModel):
    strategy: Strategy


class _PkgModel_PkgDep(_OrmModel):
    id: str


class _PkgModel_PkgVersion(_OrmModel):
    version: str
    install_time: datetime


class PkgModel(_OrmModel):
    source: str
    id: str
    slug: str
    name: str
    description: str
    url: str
    download_url: str
    date_published: datetime
    version: str
    folders: List[_PkgModel_PkgFolder]
    options: _PkgModel_PkgOptions
    deps: List[_PkgModel_PkgDep]
    logged_versions: List[_PkgModel_PkgVersion]


class MultiPkgModel(BaseModel):
    __root__: List[PkgModel]


class Resolver:
    source: ClassVar[str]
    name: ClassVar[str]
    strategies: ClassVar[Set[Strategy]]

    def __init__(self, manager: ManagerT) -> None:
        self.manager = manager

    @property
    def supports_rollback(self) -> bool:
        "Whether the resolver supports rollback operations."
        return Strategy.version in self.strategies

    @staticmethod
    def get_alias_from_url(value: str) -> O[str]:
        "Attempt to extract a definition name from a given URL."

    async def resolve(self, defns: Sequence[Defn]) -> Dict[Defn, Any]:
        "Resolve add-on definitions into packages."
        results = await gather(self.resolve_one(d, None) for d in defns)
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: O[Any]) -> m.Pkg:
        "Resolve an individual definition into a package."
        raise NotImplementedError

    @classmethod
    async def collect_items(
        cls, web_client: aiohttp.ClientSession
    ) -> AsyncIterable[_CatalogueEntryDefaultFields]:
        "Yield add-ons from source for cataloguing."
        return
        yield


if TYPE_CHECKING:

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
        dependencies: List[CurseAddon_FileDependency]
        modules: List[CurseAddon_FileModules]
        exposeAsAlternative: O[bool]
        gameVersion: List[str]  # e.g. '8.3.0'
        gameVersionFlavor: Literal['wow_classic', 'wow_retail']

    class CurseAddon(TypedDict):
        id: int
        name: str  # User-facing add-on name
        websiteUrl: str  # e.g. 'https://www.curseforge.com/wow/addons/molinari'
        summary: str  # One-line description of the add-on
        downloadCount: int  # Total number of downloads
        latestFiles: List[CurseAddon_File]
        slug: str  # URL slug; 'molinari' in 'https://www.curseforge.com/wow/addons/molinari'
        dateReleased: str  # ISO datetime of latest release


class CurseResolver(Resolver):
    source = 'curse'
    name = 'CurseForge'
    strategies = {
        Strategy.default,
        Strategy.latest,
        Strategy.curse_latest_beta,
        Strategy.curse_latest_alpha,
        Strategy.any_flavour,
        Strategy.version,
    }

    # Reference: https://twitchappapi.docs.apiary.io/
    addon_api_url = URL('https://addons-ecs.forgesvc.net/api/v2/addon')

    @staticmethod
    def get_alias_from_url(value: str) -> O[str]:
        url = URL(value)
        if url.host == 'www.wowace.com' and len(url.parts) > 2 and url.parts[1] == 'projects':
            return url.parts[2].lower()
        elif (
            url.host == 'www.curseforge.com'
            and len(url.parts) > 3
            and url.parts[1:3] == ('wow', 'addons')
        ):
            return url.parts[3].lower()

    async def resolve(self, defns: Sequence[Defn]) -> Dict[Defn, Any]:
        from aiohttp import ClientResponseError

        from .manager import cache_response

        catalogue = await self.manager.synchronise()

        defns_to_ids = {d: (d.id or catalogue.curse_slugs.get(d.alias) or d.alias) for d in defns}
        numeric_ids = {i for i in defns_to_ids.values() if i.isdigit()}
        try:
            json_response = await cache_response(
                self.manager,
                self.addon_api_url,
                300,
                request_kwargs={'method': 'POST', 'json': list(numeric_ids)},
            )
        except ClientResponseError as error:
            if error.status != 404:
                raise
            json_response = []

        api_results: Dict[str, CurseAddon] = {str(r['id']): r for r in json_response}
        results = await gather(
            self.resolve_one(d, api_results.get(i)) for d, i in defns_to_ids.items()
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: O[CurseAddon]) -> m.Pkg:
        if not metadata:
            raise E.PkgNonexistent

        if defn.strategy not in self.strategies:
            raise E.PkgStrategyUnsupported(defn.strategy)

        if defn.strategy is Strategy.version:

            from .manager import cache_response

            files = await cache_response(
                self.manager,
                self.addon_api_url / str(metadata['id']) / 'files',
                3600,
                label=f'Fetching metadata from {self.name}',
            )

            def is_match(f: CurseAddon_File):
                return defn.version == f['displayName']

        else:

            files = metadata['latestFiles']

            def is_not_libless(f: CurseAddon_File):
                # There's also an 'isAlternate' field that's missing from some
                # 50 lib-less files from c. 2008.  'exposeAsAlternative' is
                # absent from the /file endpoint
                return not f['exposeAsAlternative']

            if defn.strategy is Strategy.any_flavour:

                def supports_game_version(f: CurseAddon_File):
                    return True

            else:
                classic_version_prefix = '1.13'
                flavour = 'wow_classic' if self.manager.config.is_classic else 'wow_retail'

                def supports_game_version(f: CurseAddon_File):
                    # Files can belong both to retail and classic
                    # but ``gameVersionFlavor`` can only be one of
                    # 'wow_retail' or 'wow_classic'.  To spice things up,
                    # ``gameVersion`` might not be populated so we still have to
                    # check the value of ``gameVersionFlavor``
                    return f['gameVersionFlavor'] == flavour or any(
                        v.startswith(classic_version_prefix) is self.manager.config.is_classic
                        for v in f['gameVersion']
                    )

            if defn.strategy is Strategy.latest:

                def has_release_type(f: CurseAddon_File):
                    return True

            elif defn.strategy is Strategy.curse_latest_beta:

                def has_release_type(f: CurseAddon_File):
                    return f['releaseType'] == 2

            elif defn.strategy is Strategy.curse_latest_alpha:

                def has_release_type(f: CurseAddon_File):
                    return f['releaseType'] == 3

            else:

                def has_release_type(f: CurseAddon_File):
                    return f['releaseType'] == 1

            def is_match(f: CurseAddon_File):
                return is_not_libless(f) and supports_game_version(f) and has_release_type(f)

        if not files:
            raise E.PkgFileUnavailable('no files available for download')
        try:
            file = max(
                filter(is_match, files),
                # The ``id`` is just a counter so we don't have to go digging around dates
                key=lambda f: f['id'],
            )
        except ValueError:
            raise E.PkgFileUnavailable(
                f'no files compatible with {self.manager.config.game_flavour} '
                f'using {defn.strategy.name!r} strategy'
            )

        return m.Pkg(
            source=self.source,
            id=str(metadata['id']),
            slug=metadata['slug'],
            name=metadata['name'],
            description=metadata['summary'],
            url=metadata['websiteUrl'],
            download_url=file['downloadUrl'],
            date_published=parse_datetime(file['fileDate']),
            version=file['displayName'],
            options=m.PkgOptions(strategy=defn.strategy.name),
            deps=[m.PkgDep(id=str(d['addonId'])) for d in file['dependencies'] if d['type'] == 3],
        )

    @classmethod
    async def collect_items(
        cls, web_client: aiohttp.ClientSession
    ) -> AsyncIterable[_CatalogueEntryDefaultFields]:
        classic_version_prefix = '1.13'
        flavours = ('retail', 'classic')

        def excise_flavours(files: List[CurseAddon_File]):
            for c in flavours:
                if any(f['gameVersionFlavor'] == f'wow_{c}' for f in files):
                    yield c
                elif any(
                    v.startswith(classic_version_prefix) is (c == 'classic')
                    for f in files
                    for v in f['gameVersion']
                ):
                    yield c

        step = 1000
        sort_order = '3'  # Alphabetical
        for index in count(0, step):
            async with web_client.get(
                (cls.addon_api_url / 'search').with_query(
                    gameId='1', sort=sort_order, pageSize=step, index=index
                )
            ) as response:
                json_response: List[CurseAddon] = await response.json()

            if not json_response:
                break

            for item in json_response:
                folders = uniq(
                    tuple(m['foldername'] for m in f['modules'])
                    for f in item['latestFiles']
                    if not f['exposeAsAlternative']
                )
                yield _CatalogueEntryDefaultFields(
                    source=cls.source,
                    id=str(item['id']),
                    slug=item['slug'],
                    name=item['name'],
                    game_compatibility=set(excise_flavours(item['latestFiles'])),
                    folders=folders,
                    download_count=item['downloadCount'],
                    last_updated=item['dateReleased'],
                )


if TYPE_CHECKING:

    class WowiCommonTerms(TypedDict):
        UID: str  # Unique add-on ID
        UICATID: str  # ID of category add-on is placed in
        UIVersion: str  # Add-on version
        UIDate: int  # Upload date expressed as unix epoch
        UIName: str  # User-facing add-on name
        UIAuthorName: str

    class WowiCompatibilityEntry(TypedDict):
        version: str  # Game version, e.g. '8.3.0'
        name: str  # Xpac or patch name, e.g. "Visions of N'Zoth" for 8.3.0

    class WowiListApiItem(WowiCommonTerms):
        UIFileInfoURL: str  # Add-on page on WoWI
        UIDownloadTotal: str  # Total number of downloads
        UIDownloadMonthly: str  # Number of downloads in the last month and not 'monthly'
        UIFavoriteTotal: str
        UICompatibility: O[List[WowiCompatibilityEntry]]  # ``null`` if would be empty
        UIDir: List[str]  # Names of folders contained in archive
        UIIMG_Thumbs: O[List[str]]  # Thumbnail URLs; ``null`` if would be empty
        UIIMGs: O[List[str]]  # Full-size image URLs; ``null`` if would be empty
        # There are only two add-ons on the entire list with siblings
        # (they refer to each other). I don't know if this was meant to capture
        # dependencies (probably not) but it's so underused as to be worthless.
        # ``null`` if would be empty
        UISiblings: O[List[str]]
        UIDonationLink: O[str]  # Absent from the first item on the list (!)

    class WowiDetailsApiItem(WowiCommonTerms):
        UIMD5: O[str]  # Archive hash, ``null` when UI is pending
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
    strategies = {Strategy.default}

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

    list_api_items: O[Dict[str, WowiListApiItem]] = None

    @staticmethod
    def get_alias_from_url(value: str) -> O[str]:
        url = URL(value)
        if (
            url.host in {'wowinterface.com', 'www.wowinterface.com'}
            and len(url.parts) == 3
            and url.parts[1] == 'downloads'
        ):
            if url.name == 'landing.php':
                source_id = url.query.get('fileid')
                if source_id:
                    return source_id
            elif url.name == 'fileinfo.php':
                source_id = url.query.get('id')
                if source_id:
                    return source_id
            else:
                match = re.match(r'^(?:download|info)(?P<id>\d+)', url.name)
                if match:
                    return match.group('id')

    async def resolve(self, defns: Sequence[Defn]) -> Dict[Defn, Any]:
        from aiohttp import ClientResponseError

        from .manager import cache_response

        async with self.manager.locks['load WoWI catalogue']:
            if self.list_api_items is None:
                list_api_items = await cache_response(
                    self.manager,
                    self.list_api_url,
                    3600,
                    label=f'Synchronising {self.name} catalogue',
                )
                self.list_api_items = {i['UID']: i for i in list_api_items}

        defns_to_ids = {d: ''.join(takewhile(str.isdigit, d.alias)) for d in defns}
        numeric_ids = {i for i in defns_to_ids.values() if i.isdigit()}
        try:
            details_api_items = await cache_response(
                self.manager, self.details_api_url / f'{",".join(numeric_ids)}.json', 300
            )
        except ClientResponseError as error:
            if error.status != 404:
                raise
            details_api_items = []

        combined_items = {
            i['UID']: cast('WowiCombinedItem', {**self.list_api_items[i['UID']], **i})
            for i in details_api_items
        }
        results = await gather(
            self.resolve_one(d, combined_items.get(i)) for d, i in defns_to_ids.items()
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: O[WowiCombinedItem]) -> m.Pkg:
        if not metadata:
            raise E.PkgNonexistent

        if defn.strategy not in self.strategies:
            raise E.PkgStrategyUnsupported(defn.strategy)

        return m.Pkg(
            source=self.source,
            id=metadata['UID'],
            slug=_slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
            name=metadata['UIName'],
            description=metadata['UIDescription'],
            url=metadata['UIFileInfoURL'],
            download_url=metadata['UIDownload'],
            date_published=parse_datetime(metadata['UIDate']),
            version=metadata['UIVersion'],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )

    @classmethod
    async def collect_items(
        cls, web_client: aiohttp.ClientSession
    ) -> AsyncIterable[_CatalogueEntryDefaultFields]:
        async with web_client.get(cls.list_api_url) as response:
            list_api_items: List[WowiListApiItem] = await response.json()

        for list_item in list_api_items:
            yield _CatalogueEntryDefaultFields(
                source=cls.source,
                id=list_item['UID'],
                name=list_item['UIName'],
                slug='',
                folders=[list_item['UIDir']],
                game_compatibility={'classic', 'retail'},
                download_count=int(list_item['UIDownloadTotal']),
                last_updated=list_item['UIDate'],
            )


if TYPE_CHECKING:

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
        patch: str
        screenshot_url: str
        small_desc: str
        url: str
        version: str
        web_url: str


class TukuiResolver(Resolver):
    source = 'tukui'
    name = 'Tukui'
    strategies = {Strategy.default}

    # There's also a ``/client-api.php`` endpoint which is apparently
    # used by the Tukui client itself to check for updates for the two retail
    # UIs only.  The response body appears to be identical to ``/api.php``
    api_url = URL('https://www.tukui.org/api.php')

    retail_uis = {'-1': 'tukui', '-2': 'elvui', 'tukui': 'tukui', 'elvui': 'elvui'}

    @staticmethod
    def get_alias_from_url(value: str) -> O[str]:
        url = URL(value)
        if url.host == 'www.tukui.org' and url.path in {
            '/addons.php',
            '/classic-addons.php',
            '/download.php',
        }:
            alias = url.query.get('id') or url.query.get('ui')
            if alias:
                return alias

    async def resolve_one(self, defn: Defn, metadata: None) -> m.Pkg:
        if defn.strategy not in self.strategies:
            raise E.PkgStrategyUnsupported(defn.strategy)

        alias = ui_id = self.retail_uis.get(defn.alias)
        if not alias:
            alias = ''.join(takewhile('-'.__ne__, defn.alias))

        if self.manager.config.is_classic:
            query = 'classic-addon'
        elif ui_id:
            query = 'ui'
        else:
            query = 'addon'

        url = self.api_url.with_query({query: alias})
        async with self.manager.web_client.get(url) as response:
            # Does not 404 for non-existent add-ons but the response body is empty
            if not response.content_length:
                raise E.PkgNonexistent
            addon: Union[TukuiUi, TukuiAddon] = await response.json(content_type=None)  # text/html

        return m.Pkg(
            source=self.source,
            id=str(addon['id']),
            slug=ui_id or _slugify(f'{addon["id"]} {addon["name"]}'),
            name=addon['name'],
            description=addon['small_desc'],
            url=addon['web_url'],
            download_url=addon['url'],
            date_published=datetime.fromisoformat(addon['lastupdate']).replace(
                tzinfo=timezone.utc
            ),
            version=addon['version'],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )

    @classmethod
    async def collect_items(
        cls, web_client: aiohttp.ClientSession
    ) -> AsyncIterable[_CatalogueEntryDefaultFields]:
        for query, param in [
            ('ui', 'tukui'),
            ('ui', 'elvui'),
            ('addons', 'all'),
            ('classic-addons', 'all'),
        ]:
            async with web_client.get(cls.api_url.with_query({query: param})) as response:
                metadata = await response.json(content_type=None)  # text/html

            items: List[Union[TukuiUi, TukuiAddon]] = [metadata] if query == 'ui' else metadata
            game_compatibility = 'classic' if query == 'classic-addons' else 'retail'
            for item in items:
                yield _CatalogueEntryDefaultFields(
                    source=cls.source,
                    id=str(item['id']),
                    slug='',
                    name=item['name'],
                    folders=[],
                    game_compatibility={game_compatibility},
                    # Split Tukui and ElvUI downloads evenly between them.
                    # They both have the exact same number of downloads so
                    # I'm assuming they're being counted together.
                    # Anyway, this should help with scoring other add-ons
                    # on the Tukui catalogue higher
                    download_count=int(item['downloads']) // (2 if query == 'ui' else 1),
                    last_updated=datetime.fromisoformat(item['lastupdate']).replace(
                        tzinfo=timezone.utc
                    ),
                )


if TYPE_CHECKING:

    # Not exhaustive (as you might've guessed).  Reference:
    # https://docs.github.com/en/rest/reference/repos

    class GithubRepo(TypedDict):
        name: str  # the repo in user-or-org/repo
        full_name: str  # user-or-org/repo
        description: str
        html_url: str

    class GithubReleaseAsset(TypedDict):
        name: str  # filename
        content_type: str  # mime type
        state: Literal['starter', 'uploaded']
        browser_download_url: str

    class GithubRelease(TypedDict):
        tag_name: str  # Hopefully the version
        published_at: str  # ISO datetime
        assets: List[GithubReleaseAsset]


class GithubResolver(Resolver):
    source = 'github'
    name = 'GitHub'
    strategies = {
        Strategy.default,
        Strategy.version,
    }

    repos_api_url = URL('https://api.github.com/repos')

    @staticmethod
    def get_alias_from_url(value: str) -> O[str]:
        url = URL(value)
        if url.host == 'github.com' and len(url.parts) > 2:
            return '/'.join(url.parts[1:3])

    async def resolve_one(self, defn: Defn, metadata: None) -> m.Pkg:
        """Resolve a hypothetical add-on hosted on GitHub.

        The GitHub resolver is inspired by strongbox's
        (see https://github.com/ogri-la/strongbox/blob/develop/github-addons.md)
        and makes similar assumptions.
        The repo must have releases.  The releases must have assets
        attached to them.  instawow will not retrieve add-ons from VCS tarballs
        or 'zipballs' (i.e. from source).
        It will prioritise assets which appear to be compatible with the
        selected game flavour.
        It will *not* look for TOC files or validate the contents
        of the ZIP file in any way.
        """
        from aiohttp import ClientResponseError

        from .manager import cache_response

        if defn.strategy not in self.strategies:
            raise E.PkgStrategyUnsupported(defn.strategy)

        repo_url = self.repos_api_url / defn.alias
        try:
            project_metadata: GithubRepo = await cache_response(self.manager, repo_url, 3600)
        except ClientResponseError as error:
            if error.status == 404:
                raise E.PkgNonexistent
            raise

        if defn.strategy is Strategy.version:
            release_url = repo_url / 'releases/tags' / cast(str, defn.version)
        else:
            release_url = repo_url / 'releases/latest'
        async with self.manager.web_client.get(release_url) as response:
            if response.status == 404:
                raise E.PkgFileUnavailable('release not found')
            release_metadata: GithubRelease = await response.json()

        try:

            def is_valid_asset(asset: GithubReleaseAsset):
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

            assets = release_metadata['assets']
            matching_asset = next(
                chain(
                    (
                        a
                        for a in assets
                        if is_valid_asset(a)
                        and a['name'].endswith('-classic.zip') is self.manager.config.is_classic
                    ),
                    filter(is_valid_asset, assets),
                )
            )
        except StopIteration:
            raise E.PkgFileUnavailable

        return m.Pkg(
            source=self.source,
            id=project_metadata['full_name'],
            slug=project_metadata['full_name'].lower(),
            name=project_metadata['name'],
            description=project_metadata['description'],
            url=project_metadata['html_url'],
            download_url=matching_asset['browser_download_url'],
            date_published=parse_datetime(release_metadata['published_at']),
            version=release_metadata['tag_name'],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )


class InstawowResolver(Resolver):
    source = 'instawow'
    name = 'instawow'
    strategies = {Strategy.default}

    _addons = {
        ('0', 'weakauras-companion'),
        ('1', 'weakauras-companion-autoupdate'),
    }

    async def resolve_one(self, defn: Defn, metadata: None) -> m.Pkg:
        if defn.strategy not in self.strategies:
            raise E.PkgStrategyUnsupported(defn.strategy)

        try:
            source_id, slug = next(p for p in self._addons if defn.alias in p)
        except StopIteration:
            raise E.PkgNonexistent

        from .wa_updater import BuilderConfig, WaCompanionBuilder

        builder = WaCompanionBuilder(self.manager, BuilderConfig())
        if source_id == '1':
            await builder.build()

        return m.Pkg(
            source=self.source,
            id=source_id,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            download_url=builder.addon_file.as_uri(),
            date_published=datetime.now(timezone.utc),
            version=(await t(builder.checksum)())[:7],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )

    @classmethod
    async def collect_items(
        cls, web_client: aiohttp.ClientSession
    ) -> AsyncIterable[_CatalogueEntryDefaultFields]:
        yield _CatalogueEntryDefaultFields(
            source=cls.source,
            id='1',
            slug='weakauras-companion-autoupdate',
            name='WeakAuras Companion',
            folders=[
                ['WeakAurasCompanion'],
            ],
            game_compatibility={'retail', 'classic'},
            download_count=1,
            last_updated=datetime.now(timezone.utc),
        )
