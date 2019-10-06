from __future__ import annotations

from datetime import datetime
from enum import Enum
from functools import wraps
from itertools import takewhile
import json
from operator import itemgetter
import re
from typing import TYPE_CHECKING, cast
from typing import Any, Callable, ClassVar, Dict, List, NamedTuple, Optional, Set, Tuple

from loguru import logger
from yarl import URL

from . import exceptions as E
from .models import Pkg, PkgOptions
from .utils import ManagerAttrAccessMixin, gather, run_in_thread as t, slugify, bbegone, is_not_stale

if TYPE_CHECKING:
    from .manager import Manager


class Strategies(str, Enum):

    default = 'default'
    latest = 'latest file available'
    curse_latest_beta = 'latest beta quality file available from CurseForge'
    curse_latest_alpha = 'latest alpha quality file available from CurseForge'


class Defn(NamedTuple):

    source: str
    name: str
    strategy: Strategies = Strategies.default

    def __str__(self) -> str:
        return f'{self.source}:{self.name}'


def validate_strategy(method: Callable) -> Callable:
    @wraps(method)
    async def wrapper(self, defn: Defn, *args: Any, **kwargs: Any) -> Pkg:
        if defn.strategy in self.strategies:
            return await method(self, defn, *args, **kwargs)
        raise E.PkgStrategyUnsupported(defn.strategy)

    return wrapper


class _FileCacheMixin:

    async def _cache_json_response(self: Any, url: str, *args: Any) -> Any:
        from hashlib import md5

        filename = md5(url.encode()).hexdigest()
        path = self.config.temp_dir / f'{filename}.json'

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

    def __init__(self, *, manager: Manager) -> None:
        self.manager = manager

    @classmethod
    def decompose_url(cls, value: str) -> Optional[Tuple[str, str]]:
        raise NotImplementedError

    async def synchronise(self) -> Resolver:
        return self

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        raise NotImplementedError


class CurseResolver(Resolver, _FileCacheMixin):

    source = 'curse'
    name = 'CurseForge'
    strategies = {Strategies.default, Strategies.latest,
                  Strategies.curse_latest_beta,
                  Strategies.curse_latest_alpha}

    # https://twitchappapi.docs.apiary.io/
    addon_api_url = 'https://addons-ecs.forgesvc.net/api/v2/addon'
    slugs_url = ('https://raw.githubusercontent.com/layday/instascrape/data/'
                 'curseforge-slugs.json')   # v1

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
            slugs = await self._cache_json_response(self.slugs_url, 8, 'hours')
            self._slugs = {k: str(v) for k, v in slugs.items()}
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
    async def resolve_one(self, defn: Defn, metadata: Optional[dict]) -> Pkg:
        if not metadata:
            raise E.PkgNonexistent
        elif not metadata['latestFiles']:
            raise E.PkgFileUnavailable('no files available for download')

        def is_not_libless(file: dict) -> bool:
            # There's also an 'isAlternate' field that's missing some
            # 50 lib-less files from c. 2008.  'exposeAsAlternative' is
            # absent from the /file endpoint
            return not file['exposeAsAlternative']

        classic_version_prefix = '1.13'
        flavor = 'wow_classic' if self.config.is_classic else 'wow_retail'

        def is_compatible_with_game_version(file: dict) -> bool:
            # Files can belong both to retail and classic
            # but ``gameVersionFlavor`` can only be one of
            # 'wow_retail' or 'wow_classic'.  To spice things up,
            # ``gameVersion`` might not be populated so we still have to check
            # the value of ``gameVersionFlavor``
            return (file['gameVersionFlavor'] == flavor
                    or any(v.startswith(classic_version_prefix) is self.config.is_classic
                           for v in file['gameVersion']))

        # 1 = stable; 2 = beta; 3 = alpha
        if defn.strategy is Strategies.default:
            def has_release_type(f: dict) -> bool: return f['releaseType'] == 1
        elif defn.strategy is Strategies.curse_latest_beta:
            def has_release_type(f: dict) -> bool: return f['releaseType'] == 2
        elif defn.strategy is Strategies.curse_latest_alpha:
            def has_release_type(f: dict) -> bool: return f['releaseType'] == 3
        else:
            def has_release_type(f: dict) -> bool: return True

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

        return Pkg(origin=self.source,
                   id=metadata['id'],
                   slug=metadata['slug'],
                   name=metadata['name'],
                   description=metadata['summary'],
                   url=metadata['websiteUrl'],
                   file_id=file['id'],
                   download_url=file['downloadUrl'],
                   date_published=file['fileDate'],
                   version=file['displayName'],
                   options=PkgOptions(strategy=defn.strategy.name))


class WowiResolver(Resolver, _FileCacheMixin):

    source = 'wowi'
    name = 'WoWInterface'
    strategies = {Strategies.default}

    # https://api.mmoui.com/v3/globalconfig.json
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
    async def resolve_one(self, defn: Defn, metadata: Optional[dict]) -> Pkg:
        if not metadata:
            raise E.PkgNonexistent
        if metadata['UIPending'] == '1':
            raise E.PkgFileUnavailable('new file awaiting approval')

        # The file is only assumed to be compatible with classic if 'WoW Classic'
        # is listed under compatibility, and incompatible with retail if
        # 'WoW Classic' is the sole element in the array.  I'm not sure
        # when 'UICompatibility' was added but it's very often not populated
        # for retail add-ons *shrugsies*
        compatibility = {e['name'] for e in metadata['UICompatibility'] or ()}
        if self.config.is_classic:
            if 'WoW Classic' not in compatibility:
                raise E.PkgFileUnavailable('file is not compatible with classic')
        elif compatibility and not compatibility - {'WoW Classic'}:
            raise E.PkgFileUnavailable('file is only compatible with classic')

        return Pkg(origin=self.source,
                   id=metadata['UID'],
                   slug=slugify(f'{metadata["UID"]} {metadata["UIName"]}'),
                   name=metadata['UIName'],
                   description=bbegone(metadata['UIDescription']),
                   url=metadata['UIFileInfoURL'],
                   file_id=metadata['UIMD5'],
                   download_url=metadata['UIDownload'],
                   date_published=metadata['UIDate'],
                   version=metadata['UIVersion'],
                   options=PkgOptions(strategy=defn.strategy.name))


class TukuiResolver(Resolver):

    source = 'tukui'
    name = 'Tukui'
    strategies = {Strategies.default}

    api_url = URL('https://www.tukui.org/api.php')

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
    async def resolve_one(self, defn: Defn) -> Pkg:
        id_, *_ = defn.name.partition('-')
        is_ui = id_ in {'elvui', 'tukui'}

        if self.config.is_classic:
            query = 'classic-addon'
        else:
            if is_ui:
                query = 'ui'
            else:
                query = 'addon'
        url = self.api_url.with_query({query: id_})
        async with self.web_client.get(url) as response:
            if not response.content_length:
                raise E.PkgNonexistent
            addon = await response.json(content_type='text/html')

        if is_ui:
            slug = id_
            date_published = datetime.fromisoformat(addon['lastupdate'])
        else:
            slug = slugify(f'{addon["id"]} {addon["name"]}')
            date_published = addon['lastupdate']

        return Pkg(origin=self.source,
                   id=addon['id'],
                   slug=slug,
                   name=addon['name'],
                   description=addon['small_desc'],
                   url=addon['web_url'],
                   file_id=addon['lastupdate'],
                   download_url=addon['url'],
                   date_published=date_published,
                   version=addon['version'],
                   options=PkgOptions(strategy=defn.strategy.name))


class InstawowResolver(Resolver):

    source = 'instawow'
    name = 'instawow'
    strategies = {Strategies.default}

    _addons = {('0', 'weakauras-companion'),
               ('1', 'weakauras-companion-autoupdate')}

    @classmethod
    def decompose_url(cls, value: str) -> None:
        return

    async def resolve(self, defns: List[Defn]) -> Dict[Defn, Any]:
        results = await gather(self.resolve_one(d) for d in defns)
        return dict(zip(defns, results))

    @validate_strategy
    async def resolve_one(self, defn: Defn) -> Pkg:
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

        return Pkg(origin=self.source,
                   id=id_,
                   slug=slug,
                   name='WeakAuras Companion',
                   description='A WeakAuras Companion clone.',
                   url='https://github.com/layday/instawow',
                   file_id=await t(builder.checksum)(),
                   download_url=builder.file_out.as_uri(),
                   date_published=datetime.now(),
                   version='1.0.0',
                   options=PkgOptions(strategy=defn.strategy.name))
