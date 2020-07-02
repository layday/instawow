from __future__ import annotations

from datetime import datetime
import enum
from itertools import count, takewhile
import re
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    ClassVar,
    Dict,
    List,
    NamedTuple,
    Optional as O,
    Set,
    cast,
)

from pydantic import BaseModel
from yarl import URL

from . import exceptions as E, models as m
from .utils import (
    Literal,
    ManagerAttrAccessMixin,
    cached_property,
    gather,
    run_in_thread as t,
    slugify,
    uniq,
)

if TYPE_CHECKING:
    from .manager import Manager

    JsonDict = Dict[str, Any]


class Strategies(enum.Enum):
    default = enum.auto()
    latest = enum.auto()
    curse_latest_beta = enum.auto()
    curse_latest_alpha = enum.auto()
    any_flavour = enum.auto()


class Defn(NamedTuple):
    source: str
    name: str
    strategy: Strategies = Strategies.default
    source_id: O[str] = None

    @classmethod
    def from_pkg(cls, pkg: m.Pkg) -> Defn:
        return cls(
            pkg.source,
            pkg.slug,
            Strategies[pkg.options.strategy],  # type: ignore
            pkg.id,
        )

    def with_name(self, name: str) -> Defn:
        return self.__class__(self.source, name, self.strategy, self.source_id)

    def with_strategy(self, strategy: Strategies) -> Defn:
        return self.__class__(self.source, self.name, strategy, self.source_id)

    def __str__(self) -> str:
        return f'{self.source}:{self.name}'


class _CItem(BaseModel):
    source: str
    id: str
    slug: str = ''
    name: str
    compatibility: List[Literal['retail', 'classic']]
    folders: List[List[str]] = []


class MasterCatalogue(BaseModel):
    __root__: List[_CItem]

    class Config:
        keep_untouched: Any = (cached_property,)

    @classmethod
    async def collate(cls) -> MasterCatalogue:
        from types import SimpleNamespace
        from .manager import Manager, init_web_client

        resolvers = (CurseResolver, WowiResolver, TukuiResolver)

        async with init_web_client() as web_client:
            faux_manager = cast(Manager, SimpleNamespace(web_client=web_client))
            items = [a for r in resolvers async for a in r(faux_manager).collect_items()]
        catalogue = cls(__root__=items)
        return catalogue

    @cached_property
    def curse_slugs(self) -> Dict[str, str]:
        return {a.slug: a.id for a in self.__root__ if a.source == 'curse'}


class Resolver(ManagerAttrAccessMixin):
    source: ClassVar[str]
    name: ClassVar[str]
    strategies: ClassVar[Set[Strategies]]

    def __init__(self, manager: Manager) -> None:
        self.manager = manager

    def __init_subclass__(cls) -> None:
        async def wrapper(self: Resolver, defn: Defn, *args: Any, **kwargs: Any) -> m.Pkg:
            if defn.strategy in self.strategies:
                return await resolve_one(self, defn, *args, **kwargs)
            raise E.PkgStrategyUnsupported(defn.strategy)

        resolve_one = cls.resolve_one
        cls.resolve_one = wrapper

    @staticmethod
    def decompose_url(value: str) -> O[str]:
        "Attempt to extract definition names from resolvable URLs."

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        "Resolve add-on definitions into packages."
        raise NotImplementedError

    async def collect_items(self) -> AsyncIterable[_CItem]:
        "Yield add-ons from source for cataloguing."
        return
        yield


class CurseResolver(Resolver):
    source = 'curse'
    name = 'CurseForge'
    strategies = {
        Strategies.default,
        Strategies.latest,
        Strategies.curse_latest_beta,
        Strategies.curse_latest_alpha,
        Strategies.any_flavour,
    }

    # Reference: https://twitchappapi.docs.apiary.io/
    addon_api_url = URL('https://addons-ecs.forgesvc.net/api/v2/addon')

    @staticmethod
    def decompose_url(value: str) -> O[str]:
        url = URL(value)
        if url.host == 'www.wowace.com' and len(url.parts) > 2 and url.parts[1] == 'projects':
            return url.parts[2].lower()
        elif (
            url.host == 'www.curseforge.com'
            and len(url.parts) > 3
            and url.parts[1:3] == ('wow', 'addons')
        ):
            return url.parts[3].lower()

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        ids_for_defns = {
            d: (d.source_id or self.catalogue.curse_slugs.get(d.name) or d.name) for d in defns
        }
        numeric_ids = {i for i in ids_for_defns.values() if i.isdigit()}
        async with self.web_client.post(self.addon_api_url, json=list(numeric_ids)) as response:
            if response.status == 404:
                json_response = []
            else:
                json_response = await response.json()

        api_results = {str(r['id']): r for r in json_response}
        results = await gather(
            self.resolve_one(d, api_results.get(i)) for d, i in ids_for_defns.items()
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: O[JsonDict]) -> m.Pkg:
        if not metadata:
            raise E.PkgNonexistent

        files = metadata['latestFiles']
        if not files:
            raise E.PkgFileUnavailable('no files available for download')

        def is_not_libless(f: JsonDict):
            # There's also an 'isAlternate' field that's missing some
            # 50 lib-less files from c. 2008.  'exposeAsAlternative' is
            # absent from the /file endpoint
            return not f['exposeAsAlternative']

        if defn.strategy is Strategies.any_flavour:

            def is_compatible_with_game_version(f: JsonDict):
                return True

        else:
            classic_version_prefix = '1.13'
            flavour = 'wow_classic' if self.config.is_classic else 'wow_retail'

            def is_compatible_with_game_version(f: JsonDict):
                # Files can belong both to retail and classic
                # but ``gameVersionFlavor`` can only be one of
                # 'wow_retail' or 'wow_classic'.  To spice things up,
                # ``gameVersion`` might not be populated so we still have to
                # check the value of ``gameVersionFlavor``
                return f['gameVersionFlavor'] == flavour or any(
                    v.startswith(classic_version_prefix) is self.config.is_classic
                    for v in f['gameVersion']
                )

        # 1 = stable; 2 = beta; 3 = alpha
        if defn.strategy is Strategies.latest:

            def has_release_type(f: JsonDict):
                return True

        elif defn.strategy is Strategies.curse_latest_beta:

            def has_release_type(f: JsonDict):
                return f['releaseType'] == 2

        elif defn.strategy is Strategies.curse_latest_alpha:

            def has_release_type(f: JsonDict):
                return f['releaseType'] == 3

        else:

            def has_release_type(f: JsonDict):
                return f['releaseType'] == 1

        try:
            file = max(
                (
                    f
                    for f in files
                    if is_not_libless(f)
                    and is_compatible_with_game_version(f)
                    and has_release_type(f)
                ),
                # The ``id`` is just a counter so we don't have to
                # go digging around dates
                key=lambda f: f['id'],
            )
        except ValueError:
            raise E.PkgFileUnavailable(
                f'no files compatible with {self.config.game_flavour} '
                f'using {defn.strategy.name!r} strategy'
            )

        # 1 = embedded library
        # 2 = optional dependency
        # 3 = required dependency
        # 4 = tool
        # 5 = incompatible
        # 6 = include (wat)
        deps = [m.PkgDep(id=d['addonId']) for d in file['dependencies'] if d['type'] == 3]

        return m.Pkg(
            source=self.source,
            id=metadata['id'],
            slug=metadata['slug'],
            name=metadata['name'],
            description=metadata['summary'],
            url=metadata['websiteUrl'],
            file_id=file['id'],
            download_url=file['downloadUrl'],
            date_published=file['fileDate'],
            version=file['displayName'],
            options=m.PkgOptions(strategy=defn.strategy.name),
            deps=deps,
        )

    async def collect_items(self) -> AsyncIterable[_CItem]:
        classic_version_prefix = '1.13'
        flavours = ('retail', 'classic')

        def excise_compatibility(files: Any):
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
        for index in count(0, step):
            url = (self.addon_api_url / 'search').with_query(
                # fmt: off
                gameId='1',
                sort='3', # Alphabetical
                pageSize=step, index=index,
                # fmt: on
            )
            async with self.web_client.get(url) as response:
                json_response = await response.json()

            if not json_response:
                break
            for item in json_response:
                folders = uniq(
                    tuple(m['foldername'] for m in f['modules'])
                    for f in item['latestFiles']
                    if not f['exposeAsAlternative']
                )
                yield _CItem(
                    source=self.source,
                    id=item['id'],
                    slug=item['slug'],
                    name=item['name'],
                    folders=folders,
                    compatibility=list(excise_compatibility(item['latestFiles'])),
                )


class WowiResolver(Resolver):
    source = 'wowi'
    name = 'WoWInterface'
    strategies = {Strategies.default}

    # Reference: https://api.mmoui.com/v3/globalconfig.json
    # There's also a v4 API corresponding to the as yet unreleased Minion v4,
    # which is fair to assume is unstable.  They changed the naming scheme to
    # camelCase and some fields which were strings were converted to numbers.
    # Neither API provides access to classic files for multi-file add-ons and
    # 'UICompatibility' can't be relied on to enforce compatibility
    # in instawow.  The API appears to inherit the version of the _latest_
    # file to have been uploaded, which for multi-file add-ons can be the
    # classic version.  Hoooowever the download link always points to the
    # 'retail' version, which for single-file add-ons belonging to the
    # classic category would be an add-on for classic.
    list_api_url = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    details_api_url = URL('https://api.mmoui.com/v3/game/WOW/filedetails/')

    _files: O[JsonDict] = None

    @staticmethod
    def decompose_url(value: str) -> O[str]:
        url = URL(value)
        if (
            url.host in {'wowinterface.com', 'www.wowinterface.com'}
            and len(url.parts) == 3
            and url.parts[1] == 'downloads'
        ):
            if url.name == 'landing.php':
                id_ = url.query.get('fileid')
                if id_:
                    return id_
            elif url.name == 'fileinfo.php':
                id_ = url.query.get('id')
                if id_:
                    return id_
            else:
                match = re.match(r'^(?:download|info)(?P<id>\d+)', url.name)
                if match:
                    return match.group('id')

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        if self._files is None:
            from .manager import cache_json_response

            files = await cache_json_response(
                self.manager,
                self.list_api_url,
                3600,
                label=f'Synchronising {self.source} catalogue',
            )
            self._files = {i['UID']: i for i in files}

        ids_for_defns = {d: ''.join(takewhile(str.isdigit, d.name)) for d in defns}
        numeric_ids = {i for i in ids_for_defns.values() if i.isdigit()}

        url = self.details_api_url / f'{",".join(numeric_ids)}.json'
        async with self.web_client.get(url) as response:
            if response.status == 404:
                json_response = []
            else:
                json_response = await response.json()

        api_results = {r['UID']: {**self._files[r['UID']], **r} for r in json_response}
        results = await gather(
            self.resolve_one(d, api_results.get(i)) for d, i in ids_for_defns.items()
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: O[JsonDict]) -> m.Pkg:
        if not metadata:
            raise E.PkgNonexistent

        # Files "pending" are downloadable but do not have a checksum which
        # we use as a unique file identifier
        # TODO: investigate using a different field for updates
        if metadata['UIPending'] == '1':
            raise E.PkgFileUnavailable('new file awaiting approval')

        return m.Pkg(
            source=self.source,
            id=metadata['UID'],
            slug=slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
            name=metadata['UIName'],
            description=metadata['UIDescription'],
            url=metadata['UIFileInfoURL'],
            file_id=metadata['UIMD5'],
            download_url=metadata['UIDownload'],
            date_published=metadata['UIDate'],
            version=metadata['UIVersion'],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )

    async def collect_items(self) -> AsyncIterable[_CItem]:
        async with self.web_client.get(self.list_api_url) as response:
            json_response = await response.json()
        for item in json_response:
            yield _CItem(
                source=self.source,
                id=item['UID'],
                name=item['UIName'],
                folders=[item['UIDir']],
                compatibility=['retail', 'classic'],
            )


class TukuiResolver(Resolver):
    source = 'tukui'
    name = 'Tukui'
    strategies = {Strategies.default}

    api_url = URL('https://www.tukui.org/api.php')

    retail_uis = {'-1': 'tukui', '-2': 'elvui', 'tukui': 'tukui', 'elvui': 'elvui'}

    @staticmethod
    def decompose_url(value: str) -> O[str]:
        url = URL(value)
        if url.host == 'www.tukui.org' and url.path in {
            '/addons.php',
            '/classic-addons.php',
            '/download.php',
        }:
            name = url.query.get('id') or url.query.get('ui')
            if name:
                return name

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        results = await gather(self.resolve_one(d) for d in defns)
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn) -> m.Pkg:
        name = ui_name = self.retail_uis.get(defn.name)
        if not name:
            name = ''.join(takewhile('-'.__ne__, defn.name))

        if self.config.is_classic:
            query = 'classic-addon'
        elif ui_name:
            query = 'ui'
        else:
            query = 'addon'

        url = self.api_url.with_query({query: name})
        async with self.web_client.get(url) as response:
            if not response.content_length:
                raise E.PkgNonexistent
            addon = await response.json(content_type=None)  # text/html

        return m.Pkg(
            source=self.source,
            id=addon['id'],
            slug=ui_name or slugify(f'{addon["id"]} {addon["name"]}'),
            name=addon['name'],
            description=addon['small_desc'],
            url=addon['web_url'],
            file_id=addon['version'],
            download_url=addon['url'],
            date_published=datetime.fromisoformat(addon['lastupdate']),
            version=addon['version'],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )

    async def collect_items(self) -> AsyncIterable[_CItem]:
        for query, param in [
            ('ui', 'tukui'),
            ('ui', 'elvui'),
            ('addons', 'all'),
            ('classic-addons', 'all'),
        ]:
            url = self.api_url.with_query({query: param})
            async with self.web_client.get(url) as response:
                metadata = await response.json(content_type=None)  # text/html

            if query == 'ui':
                yield _CItem(
                    source=self.source,
                    id=metadata['id'],
                    name=metadata['name'],
                    compatibility=('retail',),
                )
            else:
                compatibility = ('retail' if query == 'addons' else 'classic',)
                for item in metadata:
                    yield _CItem(
                        source=self.source,
                        id=item['id'],
                        name=item['name'],
                        compatibility=compatibility,
                    )


class InstawowResolver(Resolver):
    source = 'instawow'
    name = 'instawow'
    strategies = {Strategies.default}

    _addons = {('0', 'weakauras-companion'), ('1', 'weakauras-companion-autoupdate')}

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        results = await gather(self.resolve_one(d) for d in defns)
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn) -> m.Pkg:
        try:
            id_, slug = next(p for p in self._addons if defn.name in p)
        except StopIteration:
            raise E.PkgNonexistent

        from .wa_updater import WaCompanionBuilder, WaConfigError

        builder = WaCompanionBuilder(self.manager)
        if id_ == '1':
            try:
                await builder.build()
            except WaConfigError:
                raise E.PkgFileUnavailable('account named not provided')

        checksum = await t(builder.checksum)()
        return m.Pkg(
            source=self.source,
            id=id_,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            file_id=checksum,
            download_url=builder.addon_file.as_uri(),
            date_published=datetime.now(),
            version=checksum[:7],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )
