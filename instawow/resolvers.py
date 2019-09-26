from __future__ import annotations

from datetime import datetime
from enum import Enum
from functools import partial, wraps
from itertools import takewhile
import json
from pathlib import Path
import re
from typing import TYPE_CHECKING
from typing import Any, Callable, ClassVar, Dict, List, NamedTuple, Optional, Set, Tuple, Union

from loguru import logger
from yarl import URL

from . import exceptions as E
from .models import Pkg, PkgOptions
from .utils import ManagerAttrAccessMixin, gather, run_in_thread, slugify, bbegone, is_not_stale

try:
    from functools import singledispatchmethod      # type: ignore
except ImportError:
    from singledispatchmethod import singledispatchmethod

if TYPE_CHECKING:
    from .manager import Manager


_sentinel = object()

async_is_not_stale = run_in_thread(is_not_stale)
async_read = partial(run_in_thread(Path.read_text), encoding='utf-8')
async_write = partial(run_in_thread(Path.write_text), encoding='utf-8')


class Defn(NamedTuple):

    source: str
    name: str

    def __str__(self) -> str:
        return ':'.join(self)


class Strategies(str, Enum):

    default = 'default'
    latest = 'latest'


def validate_strategy(method: Callable) -> Callable:
    @wraps(method)
    async def wrapper(self, defns: Any, strategy_value: str, **kwargs: Any) -> Any:
        strategy = Strategies.__members__.get(strategy_value)
        if strategy in self.strategies:
            return await method(self, defns, strategy, **kwargs)
        raise E.PkgStrategyUnsupported(strategy_value)

    return wrapper


class _FileCacheMixin:

    async def _cache_json_response(self: Any, url: str, *args: Any) -> Any:
        from hashlib import md5

        filename = md5(url.encode()).hexdigest()
        path = self.config.temp_dir / f'{filename}.json'
        if await async_is_not_stale(path, *args):
            text = await async_read(path)
        else:
            async with self.web_client.get(url) as response:
                text = await response.text()
            await async_write(path, text)

        return json.loads(text)


class Resolver(ManagerAttrAccessMixin):

    source: ClassVar[str]
    name: ClassVar[str]
    strategies: ClassVar[Set[Strategies]]

    def __init__(self, *, manager: Manager) -> None:
        self.manager = manager

    @classmethod
    def decompose_url(cls, uri: str) -> Optional[Tuple[str, str]]:
        raise NotImplementedError

    async def synchronise(self) -> Resolver:
        return self

    async def resolve(self, defns: List[Defn], strategy: Strategies) -> List[Pkg]:
        raise NotImplementedError


class CurseResolver(Resolver, _FileCacheMixin):

    source = 'curse'
    name = 'CurseForge'
    strategies = {Strategies.default, Strategies.latest}

    # https://twitchappapi.docs.apiary.io/
    addon_api_url = 'https://addons-ecs.forgesvc.net/api/v2/addon'
    slugs_url = ('https://raw.githubusercontent.com/layday/instascrape/data/'
                 'curseforge-slugs.json')   # v1
    folders_url = ('https://raw.githubusercontent.com/layday/instascrape/data/'
                   'curseforge-folders.json')   # v1

    _slugs: Optional[Dict[str, str]] = None

    @classmethod
    def decompose_url(cls, uri: str) -> Optional[Tuple[str, str]]:
        url = URL(uri)
        if url.host == 'www.wowace.com' \
                and len(url.parts) > 2 \
                and url.parts[1] == 'projects':
            return (cls.source, url.parts[2].lower())
        elif url.host == 'www.curseforge.com' \
                and len(url.parts) > 3 \
                and url.parts[1:3] == ('wow', 'addons'):
            return (cls.source, url.parts[3].lower())

    async def synchronise(self) -> CurseResolver:
        if self._slugs is None:
            slugs = await self._cache_json_response(self.slugs_url, 8, 'hours')
            self._slugs = {k: str(v) for k, v in slugs.items()}
        return self

    @singledispatchmethod
    @validate_strategy
    async def resolve(self, defns: List[Defn], strategy: Strategies) -> List[Pkg]:
        assert self._slugs is not None, f'{self.source} has not been synchronised'

        ids_from_defns = [self._slugs.get(d.name, d.name) for d in defns]
        numeric_ids = list({i for i in ids_from_defns if i.isdigit()})
        async with self.web_client.post(self.addon_api_url, json=numeric_ids) as response:
            if response.status == 404:
                api_results = []       # type: ignore
            else:
                api_results = await response.json()

        results = {str(r['id']): r for r in api_results}
        return await gather(self.resolve(d, strategy, _metadata=results.get(i))
                            for d, i in zip(defns, ids_from_defns))

    @resolve.register
    @validate_strategy
    async def _(self, defn: Defn, strategy: Strategies, *, _metadata: Any = _sentinel) -> Pkg:
        if _metadata is _sentinel:
            pkg, = await self.resolve([defn], strategy)
            return pkg
        else:
            metadata = _metadata

        if not metadata:
            raise E.PkgNonexistent
        elif not metadata['latestFiles']:
            raise E.PkgFileUnavailable('no files available for download')

        flavor = 'wow_classic' if self.config.is_classic else 'wow_retail'
        files = (f for f in metadata['latestFiles']
                 if not f['isAlternate']    # nolib file if true
                 and f['gameVersionFlavor'] == flavor)
        if strategy is Strategies.default:
            # 1 = stable
            # 2 = beta
            # 3 = alpha
            files = (f for f in files if f['releaseType'] == 1)
        try:
            _, file = max((f['id'], f) for f in files)
        except ValueError:
            raise E.PkgFileUnavailable('no files meet criteria')

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
                   options=PkgOptions(strategy=strategy.name))


class WowiResolver(Resolver, _FileCacheMixin):

    source = 'wowi'
    name = 'WoWInterface'
    strategies = {Strategies.default}

    # https://api.mmoui.com/v3/globalconfig.json
    list_api_url = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    details_api_url = URL('https://api.mmoui.com/v3/game/WOW/filedetails/')

    _files: Optional[Dict[str, dict]] = None

    @classmethod
    def decompose_url(cls, uri: str) -> Optional[Tuple[str, str]]:
        url = URL(uri)
        if url.host in {'wowinterface.com', 'www.wowinterface.com'} \
                and len(url.parts) == 3 \
                and url.parts[1] == 'downloads':
            if url.name == 'landing.php':
                id_ = url.query.get('fileid')
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

    @singledispatchmethod
    @validate_strategy
    async def resolve(self, defns: List[Defn], strategy: Strategies) -> List[Pkg]:
        assert self._files is not None, f'{self.source} has not been synchronised'

        ids_from_defns = [''.join(takewhile(str.isdigit, d.name)) for d in defns]
        numeric_ids = {i for i in ids_from_defns if i.isdigit()}
        url = self.details_api_url / f'{",".join(numeric_ids)}.json'
        async with self.web_client.get(url) as response:
            if response.status == 404:
                api_results = []       # type: ignore
            else:
                api_results = await response.json()

        results = {r['UID']: {**self._files[r['UID']], **r} for r in api_results}
        return await gather(self.resolve(d, strategy, _metadata=results.get(i))
                            for d, i in zip(defns, ids_from_defns))

    @resolve.register
    @validate_strategy
    async def _(self, defn: Defn, strategy: Strategies, *, _metadata: Any = _sentinel) -> Pkg:
        if _metadata is _sentinel:
            pkg, = await self.resolve([defn], strategy)
            return pkg
        else:
            metadata = _metadata

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
                   options=PkgOptions(strategy=strategy.name))


class TukuiResolver(Resolver):

    source = 'tukui'
    name = 'Tukui'
    strategies = {Strategies.default}

    api_url = URL('https://www.tukui.org/api.php')

    @classmethod
    def decompose_url(cls, uri: str) -> Optional[Tuple[str, str]]:
        url = URL(uri)
        if url.host == 'www.tukui.org' \
                and url.path in {'/addons.php', '/classic-addons.php', '/download.php'}:
            id_or_slug = url.query.get('id') or url.query.get('ui')
            if id_or_slug:
                return (cls.source, id_or_slug)

    @singledispatchmethod
    @validate_strategy
    async def resolve(self, defns: List[Defn], strategy: Strategies) -> List[Pkg]:
        return await gather(self.resolve(d, strategy) for d in defns)

    @resolve.register
    @validate_strategy
    async def _(self, defn: Defn, strategy: Strategies) -> Pkg:
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
                   options=PkgOptions(strategy=strategy.name))


class InstawowResolver(Resolver):

    source = 'instawow'
    name = 'instawow'
    strategies = {Strategies.default}

    _addons = {('0', 'weakauras-companion'),
               ('1', 'weakauras-companion-autoupdate')}

    @classmethod
    def decompose_url(cls, uri: str) -> None:
        return

    @singledispatchmethod
    @validate_strategy
    async def resolve(self, defns: List[Defn], strategy: Strategies) -> List[Pkg]:
        return await gather(self.resolve(d, strategy) for d in defns)

    @resolve.register
    @validate_strategy
    async def _(self, defn: Defn, strategy: Strategies) -> Pkg:
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
                   file_id=await run_in_thread(builder.checksum)(),
                   download_url=builder.file_out.as_uri(),
                   date_published=datetime.now(),
                   version='1.0.0',
                   options=PkgOptions(strategy=strategy.name))
