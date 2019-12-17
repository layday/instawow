from __future__ import annotations

from datetime import datetime
from enum import Enum
from functools import wraps
from itertools import takewhile
import json
from operator import itemgetter
import re
from typing import (TYPE_CHECKING, cast,
                    Any, Callable, ClassVar, Dict, List, NamedTuple, Optional, Set, Tuple)

from yarl import URL

from . import exceptions as E, models as m
from .utils import (ManagerAttrAccessMixin, gather, is_not_stale, run_in_thread as t, shasum,
                    slugify)

if TYPE_CHECKING:
    from .manager import Manager


class Strategies(Enum):
    default = 'default'
    latest = 'most recent file available'
    curse_latest_beta = 'most recent beta quality file available from CurseForge'
    curse_latest_alpha = 'most recent alpha quality file available from CurseForge'


class Defn(NamedTuple):
    source: str
    name: str
    strategy: Strategies = Strategies.default

    def with_name(self, name: str) -> Defn:
        return self.__class__(self.source, name, self.strategy)

    def with_strategy(self, strategy: Strategies) -> Defn:
        return self.__class__(self.source, self.name, strategy)

    def __str__(self) -> str:
        return f'{self.source}:{self.name}'


def validate_strategy(method: Callable) -> Callable:
    @wraps(method)
    async def wrapper(self, defn: Defn, *args: Any, **kwargs: Any) -> m.Pkg:
        if defn.strategy in self.strategies:
            return await method(self, defn, *args, **kwargs)
        raise E.PkgStrategyUnsupported(defn.strategy)

    return wrapper


class _FileCacheMixin:
    async def _cache_json_response(self: Any, url: str, *args: Any) -> Any:
        path = self.config.temp_dir / shasum(url)

        if await t(is_not_stale)(path, *args):
            text = await t(path.read_text)(encoding='utf-8')
        else:
            async with self.web_client.get(url, raise_for_status=True) as response:
                text = await response.text()
            await t(path.write_text)(text, encoding='utf-8')
        return json.loads(text)


class Resolver(ManagerAttrAccessMixin):
    source: ClassVar[str]
    name: ClassVar[str]
    strategies: ClassVar[Set[Strategies]]

    def __init__(self, manager: Manager) -> None:
        self.manager = manager

    @classmethod
    def decompose_url(cls, value: str) -> Optional[Tuple[str, str]]:
        "Attempt to extract definition names from resolvable URLs."

    async def synchronise(self) -> Resolver:
        return self

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        raise NotImplementedError


class CurseResolver(Resolver, _FileCacheMixin):
    source = 'curse'
    name = 'CurseForge'
    strategies = {Strategies.default,
                  Strategies.latest,
                  Strategies.curse_latest_beta,
                  Strategies.curse_latest_alpha}

    # https://twitchappapi.docs.apiary.io/
    addon_api_url = 'https://addons-ecs.forgesvc.net/api/v2/addon'
    slugs_url = ('https://raw.githubusercontent.com/layday/instascrape/data/'
                 'curseforge-slugs-v2.compact.json')   # v2

    _slugs: Optional[Dict[str, str]] = None

    @classmethod
    def decompose_url(cls, value: str) -> Optional[Tuple[str, str]]:
        url = URL(value)
        if (url.host == 'www.wowace.com'
                and len(url.parts) > 2
                and url.parts[1] == 'projects'):
            return (cls.source, url.parts[2].lower())
        elif (url.host == 'www.curseforge.com'
                and len(url.parts) > 3
                and url.parts[1:3] == ('wow', 'addons')):
            return (cls.source, url.parts[3].lower())

    async def synchronise(self) -> CurseResolver:
        if self._slugs is None:
            self._slugs = await self._cache_json_response(self.slugs_url, 8, 'hours')
        return self

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        slugs = cast(dict, self._slugs)
        ids_from_defns = {d: slugs.get(d.name, d.name) for d in defns}
        numeric_ids = list({i for i in ids_from_defns.values() if i.isdigit()})
        async with self.web_client.post(self.addon_api_url, json=numeric_ids) as response:
            if response.status == 404:
                json_response = []       # type: ignore
            else:
                json_response = await response.json()

        api_results = {str(r['id']): r for r in json_response}
        coros = (self.resolve_one(d, api_results.get(i))
                 for d, i in ids_from_defns.items())
        results = dict(zip(defns, await gather(coros)))
        return results

    @validate_strategy
    async def resolve_one(self, defn: Defn, metadata: Optional[dict]) -> m.Pkg:
        if not metadata:
            raise E.PkgNonexistent
        elif not metadata['latestFiles']:
            raise E.PkgFileUnavailable('no files available for download')

        def is_not_libless(f: dict) -> bool:
            # There's also an 'isAlternate' field that's missing some
            # 50 lib-less files from c. 2008.  'exposeAsAlternative' is
            # absent from the /file endpoint
            return not f['exposeAsAlternative']

        classic_version_prefix = '1.13'
        flavor = 'wow_classic' if self.config.is_classic else 'wow_retail'

        def is_compatible_with_game_version(f: dict) -> bool:
            # Files can belong both to retail and classic
            # but ``gameVersionFlavor`` can only be one of
            # 'wow_retail' or 'wow_classic'.  To spice things up,
            # ``gameVersion`` might not be populated so we still have to
            # check the value of ``gameVersionFlavor``
            return (f['gameVersionFlavor'] == flavor
                    or any(v.startswith(classic_version_prefix) is self.config.is_classic
                           for v in f['gameVersion']))

        # 1 = stable; 2 = beta; 3 = alpha
        if defn.strategy is Strategies.latest:
            def has_release_type(f: dict) -> bool: return True
        elif defn.strategy is Strategies.curse_latest_beta:
            def has_release_type(f: dict) -> bool: return f['releaseType'] == 2
        elif defn.strategy is Strategies.curse_latest_alpha:
            def has_release_type(f: dict) -> bool: return f['releaseType'] == 3
        else:
            def has_release_type(f: dict) -> bool: return f['releaseType'] == 1

        files = (f for f in metadata['latestFiles']
                 if is_not_libless(f)
                 and is_compatible_with_game_version(f)
                 and has_release_type(f))
        try:
            # The ``id`` is just a counter so we don't have to go digging around dates
            file = max(files, key=itemgetter('id'))
        except ValueError:
            raise E.PkgFileUnavailable(f'no files compatible with {self.config.game_flavour} '
                                       f'using {defn.strategy.name!r} strategy')

        # 1 = embedded library
        # 2 = optional dependency
        # 3 = required dependency
        # 4 = tool
        # 5 = incompatible
        # 6 = include (wat)
        deps = [m.PkgDep(id=d['addonId']) for d in file['dependencies']
                if d['type'] == 3]

        return m.Pkg(origin=self.source,
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
                     deps=deps)


class WowiResolver(Resolver, _FileCacheMixin):
    source = 'wowi'
    name = 'WoWInterface'
    strategies = {Strategies.default}

    # Reference: https://api.mmoui.com/v3/globalconfig.json
    # There's also a v4 API for the as yet unreleased Minion v4 which I
    # would assume is unstable.  From a cursory glance it looks like they've
    # renamed all fields in camelCase; change the type of
    # some numeric-only fields to a number; and removed 'UISiblings'
    # which was always empty
    list_api_url = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    details_api_url = URL('https://api.mmoui.com/v3/game/WOW/filedetails/')

    _files: Optional[Dict[str, dict]] = None

    @classmethod
    def decompose_url(cls, value: str) -> Optional[Tuple[str, str]]:
        url = URL(value)
        if (url.host in {'wowinterface.com', 'www.wowinterface.com'}
                and len(url.parts) == 3
                and url.parts[1] == 'downloads'):
            if url.name == 'landing.php':
                id_ = url.query.get('fileid')
                if id_:
                    return (cls.source, id_)
            elif url.name == 'fileinfo.php':
                id_ = url.query.get('id')
                if id_:
                    return (cls.source, id_)
            else:
                match = re.match(r'^(?:download|info)(?P<id>\d+)(?:-(?P<name>[^\.]+))?',
                                 url.name)
                if match:
                    id_, slug = match.groups()
                    if slug:
                        id_ = slugify(f'{id_} {slug}')
                    return (cls.source, id_)

    async def synchronise(self) -> WowiResolver:
        if self._files is None:
            files = await self._cache_json_response(self.list_api_url, 3600)
            self._files = {i['UID']: i for i in files}
        return self

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        files = cast(dict, self._files)
        ids_from_defns = {d: ''.join(takewhile(str.isdigit, d.name)) for d in defns}
        numeric_ids = {i for i in ids_from_defns.values() if i.isdigit()}
        url = self.details_api_url / f'{",".join(numeric_ids)}.json'
        async with self.web_client.get(url) as response:
            if response.status == 404:
                json_response = []       # type: ignore
            else:
                json_response = await response.json()

        api_results = {r['UID']: {**files[r['UID']], **r} for r in json_response}
        coros = (self.resolve_one(d, api_results.get(i))
                 for d, i in ids_from_defns.items())
        results = dict(zip(defns, await gather(coros)))
        return results

    @validate_strategy
    async def resolve_one(self, defn: Defn, metadata: Optional[dict]) -> m.Pkg:
        if not metadata:
            raise E.PkgNonexistent
        if metadata['UIPending'] == '1':
            raise E.PkgFileUnavailable('new file awaiting approval')

        # WoWInterface has recently moved to a multi-file setup like CurseForge
        # and they botched it, like, completely.  Classic add-on files aren't
        # included in the API response and 'UICompatibility' can include either
        # retail or classic or both (!) but the file linked to from the API
        # is always the retail version.  You can have an add-on that is
        # nominally compatible with classic but if you were to install it
        # for classic you'd get the retail version and if you were to attempt
        # to install it for retail instawow might report that it's
        # incompatible.  The way they rushed this out without an ounce of
        # thought or care for their own add-on manager and considering it
        # hasn't received a proper update closing in on 3 years makes me
        # doubt that a fix is on the horizon.  There isn't a sensible way for
        # instawow to discern what version of the game a file's compatible with
        # so it opts to not opt to do anything at all.  Good luck and godspeed.

        return m.Pkg(origin=self.source,
                     id=metadata['UID'],
                     slug=slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
                     name=metadata['UIName'],
                     description=metadata['UIDescription'],
                     url=metadata['UIFileInfoURL'],
                     file_id=metadata['UIMD5'],
                     download_url=metadata['UIDownload'],
                     date_published=metadata['UIDate'],
                     version=metadata['UIVersion'],
                     options=m.PkgOptions(strategy=defn.strategy.name))


class TukuiResolver(Resolver):
    source = 'tukui'
    name = 'Tukui'
    strategies = {Strategies.default}

    api_url = URL('https://www.tukui.org/api.php')

    retail_uis = {'-1': 'tukui', '-2': 'elvui',
                  'tukui': 'tukui', 'elvui': 'elvui'}

    @classmethod
    def decompose_url(cls, value: str) -> Optional[Tuple[str, str]]:
        url = URL(value)
        if (url.host == 'www.tukui.org'
                and url.path in {'/addons.php', '/classic-addons.php', '/download.php'}):
            id_or_slug = url.query.get('id') or url.query.get('ui')
            if id_or_slug:
                return (cls.source, id_or_slug)

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        results = await gather(self.resolve_one(d) for d in defns)
        return dict(zip(defns, results))

    @validate_strategy
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
            addon = await response.json(content_type='text/html')

        return m.Pkg(origin=self.source,
                     id=addon['id'],
                     slug=ui_name or slugify(f'{addon["id"]} {addon["name"]}'),
                     name=addon['name'],
                     description=addon['small_desc'],
                     url=addon['web_url'],
                     file_id=addon['version'],
                     download_url=addon['url'],
                     date_published=datetime.fromisoformat(addon['lastupdate']),
                     version=addon['version'],
                     options=m.PkgOptions(strategy=defn.strategy.name))


class InstawowResolver(Resolver):
    source = 'instawow'
    name = 'instawow'
    strategies = {Strategies.default}

    _addons = {('0', 'weakauras-companion'),
               ('1', 'weakauras-companion-autoupdate')}

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        results = await gather(self.resolve_one(d) for d in defns)
        return dict(zip(defns, results))

    @validate_strategy
    async def resolve_one(self, defn: Defn) -> m.Pkg:
        try:
            id_, slug = next(p for p in self._addons if defn.name in p)
        except StopIteration:
            raise E.PkgNonexistent

        from .wa_updater import WaCompanionBuilder

        builder = WaCompanionBuilder(self.manager)
        if id_ == '1':
            try:
                await builder.build()
            except ValueError as error:
                raise E.PkgFileUnavailable('account name not provided') from error

        return m.Pkg(origin=self.source,
                     id=id_,
                     slug=slug,
                     name='WeakAuras Companion',
                     description='A WeakAuras Companion clone.',
                     url='https://github.com/layday/instawow',
                     file_id=await t(builder.checksum)(),
                     download_url=builder.file_out.as_uri(),
                     date_published=datetime.now(),
                     version='1.0.0',
                     options=m.PkgOptions(strategy=defn.strategy.name))
