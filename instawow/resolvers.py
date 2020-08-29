from __future__ import annotations

from datetime import datetime
import enum
from itertools import chain, count, takewhile
import re
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterable,
    ClassVar,
    Dict,
    List,
    Optional as O,
    Sequence,
    Set,
    Tuple,
    cast,
)

from pydantic import BaseModel
from yarl import URL

from . import exceptions as E, models as m
from .utils import Literal, cached_property, gather, run_in_thread as t, slugify, uniq

if TYPE_CHECKING:
    from .manager import Manager

    JsonDict = Dict[str, Any]


class Strategies(enum.Enum):
    default = 'default'
    latest = 'latest'
    curse_latest_beta = 'curse_latest_beta'
    curse_latest_alpha = 'curse_latest_alpha'
    any_flavour = 'any_flavour'
    version = 'version'


class Defn(BaseModel):
    source: str
    source_id: O[str] = None
    name: str
    strategy: Strategies = Strategies.default
    strategy_vals: Tuple[str, ...] = ()

    @classmethod
    def from_pkg(cls, pkg: m.Pkg) -> Defn:
        defn = cls(
            source=pkg.source, source_id=pkg.id, name=pkg.slug, strategy=pkg.options.strategy
        )
        if defn.strategy is Strategies.version:
            defn.strategy_vals = (pkg.version,)
        return defn

    @classmethod
    def get(cls, source: str, name: str) -> Defn:
        return cls(source=source, name=name)

    def with_(self, **kwargs: Any) -> Defn:
        return self.__class__(**{**self.__dict__, **kwargs})

    def with_version(self, version: str) -> Defn:
        return self.with_(strategy='version', strategy_vals=(version,))

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, self.__class__):
            other = tuple(other.__dict__.values())
        return tuple(self.__dict__.values()) == other

    def __hash__(self) -> int:
        return hash(tuple(self.__dict__.values()))

    def __str__(self) -> str:
        return f'{self.source}:{self.name}'


class _CatalogueEntry(BaseModel):
    source: str
    id: str
    slug: str = ''
    name: str
    compatibility: Set[Literal['retail', 'classic']] = {'retail', 'classic'}
    folders: List[List[str]] = []


class MasterCatalogue(BaseModel):
    __root__: List[_CatalogueEntry]

    class Config:
        keep_untouched = (cast(Any, cached_property),)

    @classmethod
    async def collate(cls) -> MasterCatalogue:
        from types import SimpleNamespace

        from .manager import init_web_client

        resolvers = (CurseResolver, WowiResolver, TukuiResolver)

        async with init_web_client() as web_client:
            faux_manager = cast('Manager', SimpleNamespace(web_client=web_client))
            items = [a for r in resolvers async for a in r(faux_manager).collect_items()]
        catalogue = cls(__root__=items)
        return catalogue

    @cached_property
    def curse_slugs(self) -> Dict[str, str]:
        return {a.slug: a.id for a in self.__root__ if a.source == 'curse'}


class Resolver:
    source: ClassVar[str]
    name: ClassVar[str]
    strategies: ClassVar[Set[Strategies]]

    def __init__(self, manager: Manager) -> None:
        self.manager = manager

    def __init_subclass__(cls) -> None:
        async def resolve_wrapper(self: Resolver, defn: Defn, metadata: O[JsonDict]) -> m.Pkg:
            if defn.strategy in self.strategies:
                return await resolve_one(self, defn, metadata)  # type: ignore
            raise E.PkgStrategyUnsupported(defn.strategy)

        resolve_one = cls.resolve_one
        cls.resolve_one = resolve_wrapper  # type: ignore

    @property
    def supports_rollback(self) -> bool:
        "Whether the resolver supports rollback operations."
        return Strategies.version in self.strategies

    @staticmethod
    def get_name_from_url(value: str) -> O[str]:
        "Attempt to extract a definition name from a given URL."

    async def resolve(self, defns: Sequence[Defn]) -> Dict[Defn, Any]:
        "Resolve add-on definitions into packages."
        results = await gather(self.resolve_one(d, None) for d in defns)
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: O[JsonDict]) -> m.Pkg:
        "Resolve an individual definition into a package."
        raise NotImplementedError

    async def collect_items(self) -> AsyncIterable[_CatalogueEntry]:
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
        Strategies.version,
    }

    # Reference: https://twitchappapi.docs.apiary.io/
    addon_api_url = URL('https://addons-ecs.forgesvc.net/api/v2/addon')

    @staticmethod
    def get_name_from_url(value: str) -> O[str]:
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

        from .manager import cache_json_response

        ids_for_defns = {
            d: (d.source_id or self.manager.catalogue.curse_slugs.get(d.name) or d.name)
            for d in defns
        }
        numeric_ids = {i for i in ids_for_defns.values() if i.isdigit()}
        try:
            json_response = await cache_json_response(
                self.manager,
                self.addon_api_url,
                300,
                request_kwargs={'method': 'POST', 'json': list(numeric_ids)},
            )
        except ClientResponseError as error:
            if error.status != 404:
                raise
            json_response = []

        api_results = {str(r['id']): r for r in json_response}
        results = await gather(
            self.resolve_one(d, api_results.get(i)) for d, i in ids_for_defns.items()
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: O[JsonDict]) -> m.Pkg:
        if not metadata:
            raise E.PkgNonexistent

        if defn.strategy is Strategies.version:

            from .manager import cache_json_response

            files = await cache_json_response(
                self.manager,
                self.addon_api_url / str(metadata['id']) / 'files',
                3600,
                label=f'Fetching metadata from {self.name}',
            )

            def is_compatible(f: JsonDict):
                return defn.strategy_vals[0] == f['displayName']

        else:

            files = metadata['latestFiles']

            def is_not_libless(f: JsonDict):
                # There's also an 'isAlternate' field that's missing from some
                # 50 lib-less files from c. 2008.  'exposeAsAlternative' is
                # absent from the /file endpoint
                return not f['exposeAsAlternative']

            if defn.strategy is Strategies.any_flavour:

                def supports_game_version(f: JsonDict):
                    return True

            else:
                classic_version_prefix = '1.13'
                flavour = 'wow_classic' if self.manager.config.is_classic else 'wow_retail'

                def supports_game_version(f: JsonDict):
                    # Files can belong both to retail and classic
                    # but ``gameVersionFlavor`` can only be one of
                    # 'wow_retail' or 'wow_classic'.  To spice things up,
                    # ``gameVersion`` might not be populated so we still have to
                    # check the value of ``gameVersionFlavor``
                    return f['gameVersionFlavor'] == flavour or any(
                        v.startswith(classic_version_prefix) is self.manager.config.is_classic
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

            def is_compatible(f: JsonDict):
                return is_not_libless(f) and supports_game_version(f) and has_release_type(f)

        if not files:
            raise E.PkgFileUnavailable('no files available for download')
        try:
            file = max(
                filter(is_compatible, files),
                # The ``id`` is just a counter so we don't have to go digging around dates
                key=lambda f: f['id'],
            )
        except ValueError:
            raise E.PkgFileUnavailable(
                f'no files compatible with {self.manager.config.game_flavour} '
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
            download_url=file['downloadUrl'],
            date_published=file['fileDate'],
            version=file['displayName'],
            options=m.PkgOptions(strategy=defn.strategy.name),
            deps=deps,
        )

    async def collect_items(self) -> AsyncIterable[_CatalogueEntry]:
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
        sort_order = '3'  # Alphabetical
        for index in count(0, step):
            url = (self.addon_api_url / 'search').with_query(
                gameId='1', sort=sort_order, pageSize=step, index=index
            )
            async with self.manager.web_client.get(url) as response:
                json_response = await response.json()

            if not json_response:
                break
            for item in json_response:
                folders = uniq(
                    tuple(m['foldername'] for m in f['modules'])
                    for f in item['latestFiles']
                    if not f['exposeAsAlternative']
                )
                yield _CatalogueEntry(
                    source=self.source,
                    id=item['id'],
                    slug=item['slug'],
                    name=item['name'],
                    compatibility=set(excise_compatibility(item['latestFiles'])),
                    folders=folders,
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
    def get_name_from_url(value: str) -> O[str]:
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

        from .manager import cache_json_response

        async with self.manager.locks['load WoWI catalogue']:
            if self._files is None:
                files = await cache_json_response(
                    self.manager,
                    self.list_api_url,
                    3600,
                    label=f'Synchronising {self.name} catalogue',
                )
                self._files = {i['UID']: i for i in files}

        ids_for_defns = {d: ''.join(takewhile(str.isdigit, d.name)) for d in defns}
        numeric_ids = {i for i in ids_for_defns.values() if i.isdigit()}
        url = self.details_api_url / f'{",".join(numeric_ids)}.json'
        try:
            json_response = await cache_json_response(self.manager, url, 300)
        except ClientResponseError as error:
            if error.status != 404:
                raise
            json_response = []

        api_results = {r['UID']: {**self._files[r['UID']], **r} for r in json_response}
        results = await gather(
            self.resolve_one(d, api_results.get(i)) for d, i in ids_for_defns.items()
        )
        return dict(zip(defns, results))

    async def resolve_one(self, defn: Defn, metadata: O[JsonDict]) -> m.Pkg:
        if not metadata:
            raise E.PkgNonexistent

        # 'UIPending' is set to '1' for files awaiting approval during which
        # time 'UIMD5' is null - all other fields appear to be filled correctly
        return m.Pkg(
            source=self.source,
            id=metadata['UID'],
            slug=slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
            name=metadata['UIName'],
            description=metadata['UIDescription'],
            url=metadata['UIFileInfoURL'],
            download_url=metadata['UIDownload'],
            date_published=metadata['UIDate'],
            version=metadata['UIVersion'],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )

    async def collect_items(self) -> AsyncIterable[_CatalogueEntry]:
        async with self.manager.web_client.get(self.list_api_url) as response:
            json_response = await response.json()

        for item in json_response:
            yield _CatalogueEntry(
                source=self.source,
                id=item['UID'],
                name=item['UIName'],
                folders=[item['UIDir']],
            )


class TukuiResolver(Resolver):
    source = 'tukui'
    name = 'Tukui'
    strategies = {Strategies.default}

    api_url = URL('https://www.tukui.org/api.php')

    retail_uis = {'-1': 'tukui', '-2': 'elvui', 'tukui': 'tukui', 'elvui': 'elvui'}

    @staticmethod
    def get_name_from_url(value: str) -> O[str]:
        url = URL(value)
        if url.host == 'www.tukui.org' and url.path in {
            '/addons.php',
            '/classic-addons.php',
            '/download.php',
        }:
            name = url.query.get('id') or url.query.get('ui')
            if name:
                return name

    async def resolve_one(self, defn: Defn, metadata: Any) -> m.Pkg:
        name = ui_name = self.retail_uis.get(defn.name)
        if not name:
            name = ''.join(takewhile('-'.__ne__, defn.name))

        if self.manager.config.is_classic:
            query = 'classic-addon'
        elif ui_name:
            query = 'ui'
        else:
            query = 'addon'

        url = self.api_url.with_query({query: name})
        async with self.manager.web_client.get(url) as response:
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
            download_url=addon['url'],
            date_published=datetime.fromisoformat(addon['lastupdate']),
            version=addon['version'],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )

    async def collect_items(self) -> AsyncIterable[_CatalogueEntry]:
        for query, param, compatibility in [
            ('ui', 'tukui', 'retail'),
            ('ui', 'elvui', 'retail'),
            ('addons', 'all', 'retail'),
            ('classic-addons', 'all', 'classic'),
        ]:
            url = self.api_url.with_query({query: param})
            async with self.manager.web_client.get(url) as response:
                metadata = await response.json(content_type=None)  # text/html

            if query == 'ui':
                yield _CatalogueEntry(
                    source=self.source,
                    id=metadata['id'],
                    name=metadata['name'],
                    compatibility={compatibility},
                )
            else:
                for item in metadata:
                    yield _CatalogueEntry(
                        source=self.source,
                        id=item['id'],
                        name=item['name'],
                        compatibility={compatibility},
                    )


class GithubResolver(Resolver):
    source = 'github'
    name = 'GitHub'
    strategies = {
        Strategies.default,
        Strategies.version,
    }

    repos_api_url = URL('https://api.github.com/repos')

    @staticmethod
    def get_name_from_url(value: str) -> O[str]:
        url = URL(value)
        if url.host == 'github.com' and len(url.parts) > 2:
            return '/'.join(url.parts[1:3])

    async def resolve_one(self, defn: Defn, metadata: Any) -> m.Pkg:
        """Resolve a hypothetical add-on hosted on GitHub.

        The GitHub resolver, ahem, 'builds' on the work done by Torkus
        (see https://github.com/ogri-la/strongbox/blob/develop/github-addons.md) -
        it purports to support the different kinds of add-ons supported by strongbox
        with the exception that instawow does not look for TOC files or validate
        the contents of the ZIP file.
        instawow will attempt to prioritise add-ons compatible with your selected
        game flavour.  It will otherwise install the first file it encounters.
        instawow will only install assets attached to releases.  It will not
        install add-ons from VCS tarballs or 'zipballs' (i.e. from source).
        """
        from aiohttp import ClientResponseError

        from .manager import cache_json_response

        repo_url = self.repos_api_url / defn.name
        try:
            project_metadata = await cache_json_response(self.manager, repo_url, 3600)
        except ClientResponseError as error:
            if error.status == 404:
                raise E.PkgNonexistent
            raise

        if defn.strategy is Strategies.version:
            release_url = repo_url / 'releases/tags' / defn.strategy_vals[0]
        else:
            release_url = repo_url / 'releases/latest'
        async with self.manager.web_client.get(release_url) as response:
            if response.status == 404:
                raise E.PkgFileUnavailable('release not found')
            release_metadata = await response.json()

        try:

            def is_valid_asset(asset: JsonDict):
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

            assets = release_metadata.get('assets', [])
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
            date_published=release_metadata['published_at'],
            version=release_metadata['tag_name'],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )


class InstawowResolver(Resolver):
    source = 'instawow'
    name = 'instawow'
    strategies = {Strategies.default}

    _addons = {
        ('0', 'weakauras-companion'),
        ('1', 'weakauras-companion-autoupdate'),
    }

    async def resolve_one(self, defn: Defn, metadata: Any) -> m.Pkg:
        try:
            source_id, slug = next(p for p in self._addons if defn.name in p)
        except StopIteration:
            raise E.PkgNonexistent

        from .wa_updater import BuilderConfig, WaCompanionBuilder

        sentinel = '__sentinel__'
        builder = WaCompanionBuilder(self.manager, BuilderConfig(account=sentinel))
        if source_id == '1':
            if builder.builder_config.account == sentinel:
                raise E.PkgFileUnavailable('account name not provided')
            await builder.build()

        checksum = await t(builder.checksum)()
        return m.Pkg(
            source=self.source,
            id=source_id,
            slug=slug,
            name='WeakAuras Companion',
            description='A WeakAuras Companion clone.',
            url='https://github.com/layday/instawow',
            download_url=builder.addon_file.as_uri(),
            date_published=datetime.now(),
            version=checksum[:7],
            options=m.PkgOptions(strategy=defn.strategy.name),
        )
