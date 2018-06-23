
import asyncio
from datetime import datetime as dt, timedelta
import re
import typing as T

from parsel import Selector
from yarl import URL

from .models import CacheEntry, Pkg, PkgOptions


_EXPIRY = 3600


class BaseResolver:

    __members__ = {}

    synced: bool = False
    origin: str
    name: str

    def __init__(self, *, manager: 'Manager'):
        self.manager = manager
        self._sync_lock = asyncio.Lock(loop=manager.loop)

    def __init_subclass__(cls, origin: str, name: str):
        cls.__members__[origin] = cls
        cls.origin = origin
        cls.name = name

        orig_resolve = cls.resolve
        async def _resolve(self, *args, **kwargs):
            async with self._sync_lock:
                if not self.synced:
                    await self.sync()
                    self.synced = True
            return await orig_resolve(self, *args, **kwargs)
        cls.resolve = _resolve

    def __getattr__(self, name):
        # Delegate attribute access to the ``Manager``
        return getattr(self.manager, name)

    @classmethod
    def decompose_url(cls, url: str) -> T.Optional[T.Tuple[str, str]]:
        "Break a URL down into its component `origin` and `id`."

    async def sync(self) -> None:
        """Serves as a deferred, asynchronous `__init__`.  Do any
        preprocessing here if necessary, including writing to the cache.
        """

    async def resolve(self, id_or_slug: str, *,
                      strategy: str) -> Pkg:
        "Turn an ID or slug into a `models.Pkg`."
        raise NotImplementedError


class _CurseResolver(BaseResolver,
                     origin='curse', name='CurseForge'):

    _re_curse_url = re.compile(r'(?P<id>\d+)-(?P<slug>[a-z_-]+)')

    @classmethod
    def decompose_url(cls, url: str) -> T.Optional[T.Tuple[str, str]]:
        url = URL(url)
        if url.host in {'wow.curseforge.com', 'www.wowace.com'} \
                and len(url.parts) > 2 \
                and url.parts[1] == 'projects':
            return (cls.origin, url.parts[2])
        elif url.host == 'www.curseforge.com' \
                and len(url.parts) > 3 \
                and url.parts[1:3] == ('wow', 'addons'):
            slug = url.parts[3]
            match = cls._re_curse_url.match(slug)
            if match:
                slug = match.group('id')
            return (cls.origin, slug)

    async def resolve(self, id_or_slug: str, *,
                      strategy: str) -> Pkg:
        async with self.client.get()\
                              .get(f'https://wow.curseforge.com/projects/{id_or_slug}') \
                as response:
            if response.status != 200 \
                    or response.url.host not in {'wow.curseforge.com', 'www.wowace.com'}:
                raise self.PkgNonexistent
            content = await response.text()
        content = Selector(text=content, base_url=str(response.url))
        content.root.make_links_absolute()

        if strategy == 'canonical':
            file = content.css('.cf-recentfiles > li:first-child '
                               '.cf-recentfiles-credits-wrapper')
        else:
            file = max(map(int, content.css('.cf-recentfiles abbr::attr(data-epoch)')
                                       .extract()))
            file = content.xpath(f'//*[@class = "cf-recentfiles"]'
                                 f'//abbr[@data-epoch = "{file}"]/..')

        return Pkg(origin=self.origin,
                   id=content.xpath('''\
//div[@class = "info-label" and text() = "Project ID"]/following-sibling::div/text()'''
                                    ).extract_first().strip(),
                   slug=response.url.name,
                   name=content.css('meta[property="og:title"]::attr(content)')
                               .extract_first(),
                   description=content.css('meta[property="og:description"]::attr(content)')
                                      .extract_first(),
                   url=content.css('.view-on-curse > a::attr(href)').extract_first(),
                   file_id=URL(file.css('.overflow-tip::attr(href)')
                                   .extract_first()).name,
                   download_url=file.css('.fa-icon-download::attr(href)').extract_first(),
                   date_published=file.css('abbr::attr(data-epoch)').extract_first(),
                   version=file.css('.overflow-tip::attr(data-name)').extract_first(),
                   options=PkgOptions(strategy=strategy))


class _WowiResolver(BaseResolver,
                    origin='wowi', name='WoWInterface'):

    _data: dict

    _api_list = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    _api_details = 'https://api.mmoui.com/v3/game/WOW/filedetails/{}.json'

    _re_addon_url = re.compile(r'(?:download|info)(?P<slug>(?P<id>\d+)[^.]+)')

    @classmethod
    def decompose_url(cls, url: str) -> T.Optional[T.Tuple[str, str]]:
        url = URL(url)
        if url.host in {'wowinterface.com', 'www.wowinterface.com'} \
                and len(url.parts) == 3 \
                and url.parts[1] == 'downloads':
            match = cls._re_addon_url.match(url.name)
            if match:
                return (cls.origin, match.group('id'))

    async def sync(self) -> None:
        entry = self.db.query(CacheEntry).get((self.origin, self.origin))
        if not entry or ((entry.date_retrieved + timedelta(seconds=_EXPIRY)) <
                         dt.now()):
            async with self.client.get()\
                                  .get(self._api_list) as response:
                data = await response.read()
            new_entry = CacheEntry(origin=self.origin, id=self.origin,
                                   date_retrieved=dt.now(), contents=data)
            entry = self.db.x_replace(new_entry, entry)
        self._data = {e['UID']: e for e in entry.contents}

    async def resolve(self, id_or_slug: str, *,
                      strategy: str) -> Pkg:
        try:
            file = self._data[id_or_slug.partition('-')[0]]
        except KeyError:
            raise self.PkgNonexistent

        async with self.client.get()\
                              .get(self._api_details.format(file['UID'])) as response:
            details, = await response.json()
        if file['UIDate'] != details['UIDate']:
            raise self.CacheObsolete

        return Pkg(origin=self.origin,
                   id=file['UID'],
                   slug=self._re_addon_url.search(file['UIFileInfoURL'])
                                          .group('slug'),
                   name=file['UIName'],
                   description=details['UIDescription'],
                   url=file['UIFileInfoURL'],
                   file_id=details['UIMD5'],
                   download_url=details['UIDownload'],
                   date_published=details['UIDate'],
                   version=details['UIVersion'],
                   options=PkgOptions(strategy=strategy))


class _TukuiResolver(BaseResolver,
                     origin='tukui', name='Tukui'):

    _re_addon_url = re.compile(re.escape('https://www.tukui.org/addons.php?id=') +
                               r'(?P<id>\d+)')

    @classmethod
    def decompose_url(cls, url: str) -> T.Optional[T.Tuple[str, str]]:
        match = cls._re_addon_url.match(url)
        if match:
            return (cls.origin, match.group('id'))

    async def resolve(self, id_or_slug: str, *,
                      strategy: str) -> Pkg:
        addon_id = id_or_slug.partition('-')[0]
        async with self.client.get()\
                              .get(f'https://www.tukui.org/api.php?addon={addon_id}') \
                as response:
            if not response.content_length:
                raise self.PkgNonexistent
            addon = await response.json(content_type='text/html')

        return Pkg(origin=self.origin,
                   id=addon['id'],
                   slug=f'{addon["id"]}-{addon["name"]}',
                   name=addon['name'],
                   description=addon['small_desc'],
                   url=addon['web_url'],
                   file_id=addon['lastupdate'],
                   download_url=addon['url'],
                   date_published=addon['lastupdate'],
                   version=addon['version'],
                   options=PkgOptions(strategy=strategy))
