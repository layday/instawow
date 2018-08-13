
import asyncio
import re
import typing as T

from parsel import Selector
from yarl import URL

from .models import Pkg, PkgOptions
from .utils import slugify


__all__ = ('CurseResolver', 'WowiResolver', 'TukuiResolver')


class Resolver:

    origin: str
    name: str

    def __init__(self, *, manager: 'Manager') -> None:
        self.manager = manager

    def __getattr__(self, name: str) -> T.Any:
        # Delegate attribute access to the manager
        return getattr(self.manager, name)

    @classmethod
    def decompose_url(cls, url: str) -> T.Optional[T.Tuple[str, str]]:
        "Break a URL down to its component `origin` and `id`."
        raise NotImplementedError

    async def resolve(self, id_or_slug: str, *, strategy: str) -> Pkg:
        "Turn an ID or slug into a `models.Pkg`."
        raise NotImplementedError


class CurseResolver(Resolver):

    origin = 'curse'
    name = 'CurseForge'

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
            return (cls.origin, url.parts[3])

    async def resolve(self, id_or_slug, *, strategy):
        async with self.client.get()\
                              .get('https://wow.curseforge.com/projects/' +
                                   id_or_slug) as response:
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


class WowiResolver(Resolver):

    origin = 'wowi'
    name = 'WoWInterface'

    _api_list = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    _api_details = 'https://api.mmoui.com/v3/game/WOW/filedetails/{}.json'

    def __init__(self, *, manager):
        super().__init__(manager=manager)
        self._sync_lock = asyncio.Lock(loop=self.loop)
        self._sync_data = None

    @classmethod
    def decompose_url(cls, url):
        url = URL(url)
        if url.host in {'wowinterface.com', 'www.wowinterface.com'} \
                and len(url.parts) == 3 \
                and url.parts[1] == 'downloads':
            id_ = ''.join(c for c in url.name.split('-')[0] if c.isdigit())
            if id_:
                return (cls.origin, id_)

    async def _sync(self):
        async with self._sync_lock:
            if not self._sync_data:
                async with self.client.get()\
                                      .get(self._api_list) as response:
                    self._sync_data = {i['UID']: i for i in (await response.json())}
            return self._sync_data

    async def resolve(self, id_or_slug, *, strategy):
        try:
            addon = (await self._sync())[id_or_slug.partition('-')[0]]
        except KeyError:
            raise self.PkgNonexistent
        async with self.client.get()\
                              .get(self._api_details.format(addon['UID'])) as response:
            addon_details, = await response.json()

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
                   options=PkgOptions(strategy=strategy))


class TukuiResolver(Resolver):

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
        async with self.client.get()\
                              .get('https://www.tukui.org/api.php?addon=' +
                                   id_or_slug.partition('-')[0]) as response:
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
