
from __future__ import annotations

__all__ = ('CurseResolver', 'WowiResolver', 'TukuiResolver', 'InstawowResolver')

import asyncio
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Optional, Set, Tuple

from yarl import URL

from . import exceptions as E
from .models import Pkg, PkgOptions
from .utils import ManagerAttrAccessMixin, slugify

if TYPE_CHECKING:
    from .manager import Manager


_DecomposeParts = Optional[Tuple[str, str]]


class Strategies(str, Enum):

    default = 'default'
    latest = 'latest'
    canonical = 'default'   #: alias

    @classmethod
    def validate(cls, method: Callable) -> Callable:
        def wrapper(self, id_or_slug: str, *, strategy: str) -> Callable:
            try:
                strategy_enum = cls[strategy]
            except KeyError:
                pass
            else:
                if strategy_enum in self.strategies:
                    return method(self, id_or_slug, strategy=strategy_enum)
            raise E.PkgStrategyInvalid(strategy)

        return wrapper


class Resolver(ManagerAttrAccessMixin):

    origin: ClassVar[str]
    name: ClassVar[str]
    strategies: ClassVar[Set[Strategies]]

    def __init__(self, *, manager: Manager) -> None:
        self.manager = manager

    @classmethod
    def decompose_url(cls, uri: str) -> _DecomposeParts:
        "Break a URL down to its component `origin` and `id`."
        raise NotImplementedError

    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg:
        "Turn an ID or slug into a `models.Pkg`."
        raise NotImplementedError


class CurseResolver(Resolver):

    origin = 'curse'
    name = 'CurseForge'
    strategies = {Strategies.default, Strategies.latest}

    cf_url = URL('https://wow.curseforge.com/projects/')

    @classmethod
    def decompose_url(cls, uri: str) -> _DecomposeParts:
        url = URL(uri)
        if url.host in {'wow.curseforge.com', 'www.wowace.com'} \
                and len(url.parts) > 2 \
                and url.parts[1] == 'projects':
            return (cls.origin, url.parts[2])
        elif url.host == 'www.curseforge.com' \
                and len(url.parts) > 3 \
                and url.parts[1:3] == ('wow', 'addons'):
            return (cls.origin, url.parts[3])

    @Strategies.validate
    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg:
        from parsel import Selector

        async with self.client.get()\
                              .get(self.cf_url.with_name(id_or_slug)) as response:
            if response.status != 200 \
                    or response.url.host not in {'wow.curseforge.com', 'www.wowace.com'}:
                raise E.PkgNonexistent
            content = await response.text()
        content = Selector(text=content, base_url=str(response.url))
        content.root.make_links_absolute()

        if strategy is Strategies.default:
            file = content.css('.cf-recentfiles > li:first-child '
                               '.cf-recentfiles-credits-wrapper')
        elif strategy is Strategies.latest:
            file = max(map(int, content.css('.cf-recentfiles abbr::attr(data-epoch)')
                                       .getall()))
            file = content.xpath(f'//*[@class = "cf-recentfiles"]'
                                 f'//abbr[@data-epoch = "{file}"]/..')

        return Pkg(origin=self.origin,
                   id=content.xpath('''\
//div[@class = "info-label" and text() = "Project ID"]/following-sibling::div/text()'''
                                    ).get().strip(),
                   slug=response.url.name,
                   name=content.css('meta[property="og:title"]::attr(content)').get(),
                   description=content.css('meta[property="og:description"]'
                                           '::attr(content)').get(),
                   url=content.css('.view-on-curse > a::attr(href)').get(),
                   file_id=URL(file.css('.overflow-tip::attr(href)').get()).name,
                   download_url=file.css('.fa-icon-download::attr(href)').get(),
                   date_published=file.css('abbr::attr(data-epoch)').get(),
                   version=file.css('.overflow-tip::attr(data-name)').get(),
                   options=PkgOptions(strategy=strategy.name))


class WowiResolver(Resolver):

    origin = 'wowi'
    name = 'WoWInterface'
    strategies = {Strategies.default}

    # https://api.mmoui.com/v3/globalconfig.json
    list_api_url = URL('https://api.mmoui.com/v3/game/WOW/filelist.json')
    details_api_url = URL('https://api.mmoui.com/v3/game/WOW/filedetails/')

    def __init__(self, *, manager: Manager) -> None:
        super().__init__(manager=manager)
        self.files: Any = None
        self._sync_lock = asyncio.Lock(loop=self.loop)

    async def _sync(self) -> None:
        async with self._sync_lock:
            if not self.files:
                async with self.client.get()\
                                      .get(self.list_api_url) as response:
                    self.files = {i['UID']: i for i in await response.json()}

                async def noop() -> None:
                    pass
                setattr(self, '_sync', noop)

    @classmethod
    def decompose_url(cls, uri: str) -> _DecomposeParts:
        url = URL(uri)
        if url.host in {'wowinterface.com', 'www.wowinterface.com'} \
                and len(url.parts) == 3 \
                and url.parts[1] == 'downloads':
            if url.name == 'landing.php':
                id_ = url.query.get('fileid')
                if id_:
                    return (cls.origin, id_)
            elif url.name.startswith('info'):
                from itertools import takewhile
                id_ = ''.join(takewhile(str.isdigit, url.name[4:]))
                if id_:
                    return (cls.origin, id_)

    @Strategies.validate
    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg:
        await self._sync()
        try:
            addon = self.files[id_or_slug.partition('-')[0]]
        except KeyError:
            raise E.PkgNonexistent

        url = self.details_api_url.with_name(f'{addon["UID"]}.json')
        async with self.client.get()\
                              .get(url) as response:
            addon_details, = await response.json()
        if addon_details['UIPending'] == '1':
            raise E.PkgTemporarilyUnavailable

        return Pkg(origin=self.origin,
                   id=addon['UID'],
                   slug=slugify(f'{addon["UID"]} {addon["UIName"]}'),
                   name=addon['UIName'],
                   description=addon_details['UIDescription'],
                   url=addon['UIFileInfoURL'],
                   file_id=addon_details['UIMD5'],
                   download_url=addon_details['UIDownload'],
                   date_published=addon_details['UIDate'],
                   version=addon_details['UIVersion'],
                   options=PkgOptions(strategy=strategy.name))


class TukuiResolver(Resolver):

    origin = 'tukui'
    name = 'Tukui'
    strategies = {Strategies.default}

    api_url = URL('https://www.tukui.org/api.php')

    @classmethod
    def decompose_url(cls, uri: str) -> _DecomposeParts:
        url = URL(uri)
        if url.host == 'www.tukui.org' \
                and url.path in {'/addons.php', '/download.php'}:
            id_or_slug = url.query.get('id') or url.query.get('ui')
            if id_or_slug:
                return (cls.origin, id_or_slug)

    @Strategies.validate
    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg:
        id_or_slug = id_or_slug.partition('-')[0]
        is_ui = id_or_slug in {'elvui', 'tukui'}

        url = self.api_url.with_query({'ui' if is_ui else 'addon': id_or_slug})
        async with self.client.get()\
                              .get(url) as response:
            if not response.content_length:
                raise E.PkgNonexistent
            addon = await response.json(content_type='text/html')

        return Pkg(origin=self.origin,
                   id=addon['id'],
                   slug=id_or_slug if is_ui else slugify(f'{addon["id"]} {addon["name"]}'),
                   name=addon['name'],
                   description=addon['small_desc'],
                   url=addon['web_url'],
                   file_id=addon['lastupdate'],
                   download_url=addon['url'],
                   date_published=(datetime.fromisoformat(addon['lastupdate'])
                                   if is_ui else addon['lastupdate']),
                   version=addon['version'],
                   options=PkgOptions(strategy=strategy.name))


class InstawowResolver(Resolver):

    origin = 'instawow'
    name = 'instawow'
    strategies = {Strategies.default}

    @classmethod
    def decompose_url(cls, uri: str) -> None:
        return

    @Strategies.validate
    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg:
        if id_or_slug not in {'0', 'weakauras-companion'}:
            raise E.PkgNonexistent

        from .wa_updater import WaCompanionBuilder
        builder = WaCompanionBuilder(self.manager)

        return Pkg(origin=self.origin,
                   id='0',
                   slug='weakauras-companion',
                   name=self.name,
                   description='A WeakAuras Companion wannabe.',
                   url='https://github.com/layday/instawow',
                   file_id=await self.loop.run_in_executor(None, builder.checksum),
                   download_url=builder.file_out.as_uri(),
                   date_published=datetime.now(),
                   version='1.0.0',
                   options=PkgOptions(strategy=strategy.name))
