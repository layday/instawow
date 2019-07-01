
from __future__ import annotations

__all__ = ('Strategies', 'Pkg_',
           'CurseResolver', 'WowiResolver', 'TukuiResolver', 'InstawowResolver')

import asyncio
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, ClassVar, Optional, Set, Tuple

from yarl import URL

from . import exceptions as E
from .models import Pkg, PkgCoercer, PkgOptions
from .utils import ManagerAttrAccessMixin, slugify

if TYPE_CHECKING:
    from .manager import Manager


class Strategies(str, Enum):

    default = 'default'
    latest = 'latest'

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


class Pkg_(PkgCoercer):

    def __call__(self, **kwargs: Any) -> Pkg:
        return Pkg(**self.dict(), **kwargs)


class Resolver(ManagerAttrAccessMixin):

    origin: ClassVar[str]
    name: ClassVar[str]
    strategies: ClassVar[Set[Strategies]]

    def __init__(self, *, manager: Manager) -> None:
        self.manager = manager

    @classmethod
    def decompose_url(cls, uri: str) -> Optional[Tuple[str, str]]:
        "Break a URL down to its component `origin` and `id`."
        raise NotImplementedError

    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg_:
        "Turn an ID or slug into a `Pkg_`."
        raise NotImplementedError

    async def list(self):
        "Crawl the service and yield a list of `Pkg_`."
        raise NotImplementedError


class CurseResolver(Resolver):

    origin = 'curse'
    name = 'CurseForge'
    strategies = {Strategies.default, Strategies.latest}

    curse_url = URL('https://www.curseforge.com/wow/addons')
    # https://twitchappapi.docs.apiary.io/
    addon_api_url = URL('https://addons-ecs.forgesvc.net/api/v2/addon')

    @classmethod
    def decompose_url(cls, uri: str) -> Optional[Tuple[str, str]]:
        url = URL(uri)
        if url.host == 'www.wowace.com' \
                and len(url.parts) > 2 \
                and url.parts[1] == 'projects':
            return (cls.origin, url.parts[2])
        elif url.host == 'www.curseforge.com' \
                and len(url.parts) > 3 \
                and url.parts[1:3] == ('wow', 'addons'):
            return (cls.origin, url.parts[3])

    @Strategies.validate
    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg_:
        from lxml.html import document_fromstring

        project_url = self.curse_url / id_or_slug
        async with self.web_client.get(project_url) as response:
            if response.status == 404:
                addon_id = id_or_slug
            else:
                html = document_fromstring(await response.text())
                addon_id, = html.xpath('//span[text() = "Project ID"]'
                                       '/following-sibling::span'
                                       '/text()')

        url = self.addon_api_url / addon_id
        async with self.web_client.get(url) as response:
            if response.status == 404:
                raise E.PkgNonexistent
            addon_metadata = await response.json()

        if strategy is Strategies.default:
            file = next(f for f in addon_metadata['latestFiles']
                        if f['id'] == addon_metadata['defaultFileId'])
        elif strategy is Strategies.latest:
            _, file = max((f['id'], f) for f in addon_metadata['latestFiles']
                          if not f['isAlternate'])

        return Pkg_(origin=self.origin,
                    id=addon_metadata['id'],
                    slug=addon_metadata['slug'],
                    name=addon_metadata['name'],
                    description=addon_metadata['summary'],
                    url=addon_metadata['websiteUrl'],
                    file_id=file['id'],
                    download_url=file['downloadUrl'],
                    date_published=file['fileDate'],
                    version=file['displayName'],
                    options=PkgOptions(strategy=strategy.name))

    async def search(self, search_pattern: str):
        from lxml.html import document_fromstring

        search_url = self.curse_url / 'search'
        params = {'search': search_pattern}
        async with self.web_client.get(search_url, params=params) as response:
            page_text = await response.text()

            if "No results for" in page_text:
                return []

            html = document_fromstring(page_text)
            rows = html.xpath(
                '//div[contains(@class, "project-listing-row")]')
            addons = []
            for row in rows:
                name = row.xpath('.//a/h3')[0].text
                path = (row.xpath('.//a[contains(@href, "wow/addons")]')[0]
                        .attrib.get('href').lstrip('/'))
                url = URL('https://www.curseforge.com') / path
                author = (row.xpath('.//a[contains(@href, "members/")]')[0]
                          .text)
                desc = (row.xpath('.//p')[0].text).strip()
                addons.append({'name': name, 'url': str(url), 'author': author,
                               'desc': desc})
            return addons


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
        self._sync_lock = asyncio.Lock()

    async def _sync(self) -> None:
        async with self._sync_lock:
            if not self.files:
                async with self.web_client.get(self.list_api_url) as response:
                    self.files = {i['UID']: i for i in await response.json()}

                async def noop() -> None:
                    pass
                setattr(self, '_sync', noop)

    @classmethod
    def decompose_url(cls, uri: str) -> Optional[Tuple[str, str]]:
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
    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg_:
        await self._sync()
        try:
            addon = self.files[id_or_slug.partition('-')[0]]
        except KeyError:
            raise E.PkgNonexistent

        url = self.details_api_url / f'{addon["UID"]}.json'
        async with self.web_client.get(url) as response:
            addon_details, = await response.json()
        if addon_details['UIPending'] == '1':
            raise E.PkgTemporarilyUnavailable

        return Pkg_(origin=self.origin,
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
    def decompose_url(cls, uri: str) -> Optional[Tuple[str, str]]:
        url = URL(uri)
        if url.host == 'www.tukui.org' \
                and url.path in {'/addons.php', '/download.php'}:
            id_or_slug = url.query.get('id') or url.query.get('ui')
            if id_or_slug:
                return (cls.origin, id_or_slug)

    @Strategies.validate
    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg_:
        id_or_slug = id_or_slug.partition('-')[0]
        is_ui = id_or_slug in {'elvui', 'tukui'}

        url = self.api_url.with_query({'ui' if is_ui else 'addon': id_or_slug})
        async with self.web_client.get(url) as response:
            if not response.content_length:
                raise E.PkgNonexistent
            addon = await response.json(content_type='text/html')

        return Pkg_(origin=self.origin,
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
    async def resolve(self, id_or_slug: str, *, strategy: Strategies) -> Pkg_:
        if id_or_slug not in {'0', 'weakauras-companion'}:
            raise E.PkgNonexistent

        from .manager import run_in_thread
        from .wa_updater import WaCompanionBuilder

        builder = WaCompanionBuilder(self.manager)

        return Pkg_(origin=self.origin,
                    id='0',
                    slug='weakauras-companion',
                    name=self.name,
                    description='A WeakAuras Companion wannabe.',
                    url='https://github.com/layday/instawow',
                    file_id=await run_in_thread(builder.checksum)(),
                    download_url=builder.file_out.as_uri(),
                    date_published=datetime.now(),
                    version='1.0.0',
                    options=PkgOptions(strategy=strategy.name))
