
import asyncio
import re
import typing as T

from parsel import Selector
from yarl import URL

from .models import Pkg, PkgOptions
from .utils import slugify


_EXPIRY = 3600


class _BaseResolver:

    origin: str
    name: str

    def __init__(self, *, manager: 'Manager') -> None:
        self._synced = False
        self._sync_lock = asyncio.Lock(loop=manager.loop)

        self.manager = manager

    def __init_subclass__(cls) -> None:
        orig_resolve = cls.resolve
        async def _resolve(self, *args, **kwargs):
            async with self._sync_lock:
                if not self._synced:
                    await self.sync()
                    self._synced = True
            return await orig_resolve(self, *args, **kwargs)
        cls.resolve = _resolve

    def __getattr__(self, name: str) -> T.Any:
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


class CurseResolver(_BaseResolver):

    origin = 'curse'
    name = 'CurseForge'

    _re_curse_url = re.compile(r'(?P<id>\d+)-(?P<slug>[a-z_-]+)')

    @classmethod
    def decompose_url(cls, url):
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

    async def resolve(self, id_or_slug, *, strategy):
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
                   options=PkgOptions(strategy=strategy))


class WowiResolver(_BaseResolver):

    origin = 'wowi'
    name = 'WoWInterface'

    _data: dict

    _api_list = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    _api_details = 'https://api.mmoui.com/v3/game/WOW/filedetails/{}.json'

    _re_addon_url = re.compile(r'(?:download|info)(?P<id>\d+)')

    @classmethod
    def decompose_url(cls, url):
        url = URL(url)
        if url.host in {'wowinterface.com', 'www.wowinterface.com'} \
                and len(url.parts) == 3 \
                and url.parts[1] == 'downloads':
            match = cls._re_addon_url.match(url.name)
            if match:
                return (cls.origin, match.group('id'))

    async def sync(self):
        async with self.client.get().get(self._api_list) as response:
            data = await response.json()
        self._data = {i['UID']: i for i in data}

    async def resolve(self, id_or_slug, *, strategy):
        try:
            file = self._data[id_or_slug.partition('-')[0]]
        except KeyError:
            raise self.PkgNonexistent
        async with self.client.get()\
                              .get(self._api_details.format(file['UID'])) as response:
            details, = await response.json()

        return Pkg(origin=self.origin,
                   id=file['UID'],
                   slug=slugify(f'{file["UID"]} {file["UIName"]}'),
                   name=file['UIName'],
                   description=details['UIDescription'],
                   url=file['UIFileInfoURL'],
                   file_id=details['UIMD5'],
                   download_url=details['UIDownload'],
                   date_published=details['UIDate'],
                   version=details['UIVersion'],
                   options=PkgOptions(strategy=strategy))


class TukuiResolver(_BaseResolver):

    origin = 'tukui'
    name = 'Tukui'

    _re_addon_url = re.compile(re.escape('https://www.tukui.org/addons.php?id=') +
                               r'(?P<id>\d+)')

    @classmethod
    def decompose_url(cls, url):
        match = cls._re_addon_url.match(url)
        if match:
            return (cls.origin, match.group('id'))

    async def resolve(self, id_or_slug, *, strategy):
        addon_id = id_or_slug.partition('-')[0]
        async with self.client.get()\
                              .get(f'https://www.tukui.org/api.php?addon={addon_id}') \
                as response:
            if not response.content_length:
                raise self.PkgNonexistent
            addon = await response.json(content_type='text/html')

        return Pkg(origin=self.origin,
                   id=addon['id'],
                   slug=slugify(f'{addon["id"]} {addon["name"]}'),
                   name=addon['name'],
                   description=addon['small_desc'],
                   url=addon['web_url'],
                   file_id=addon['lastupdate'],
                   download_url=addon['url'],
                   date_published=addon['lastupdate'],
                   version=addon['version'],
                   options=PkgOptions(strategy=strategy))
