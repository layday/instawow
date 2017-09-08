
import bz2
from collections import ChainMap
from datetime import datetime as dt, timedelta
import re
import typing

from yarl import URL

from .models import CacheEntry, Pkg, PkgFolder, PkgOptions


EXPIRY = 3600


class BaseResolver:

    __members__ = {}

    def __init__(self, *, manager):
        self.manager = manager
        self.synced = False

    def __init_subclass__(cls, origin):
        cls.__members__[origin] = cls

    async def sync(self):
        """Serves as a deferred, asynchronous `__init__`.  Do any
        preprocessing here if necessary, including writing to the cache.
        """

    def load(self):
        """Preload any data from the cache here."""

    async def resolve(self, id_or_slug, *, strategy) -> Pkg:
        """Turn an ID or slug into a `models.Pkg`."""
        raise NotImplementedError

    @classmethod
    def decompose_url(cls, url) -> typing.Tuple[str, str]:
        """Take an add-on page URL and return its corresponding origin and ID."""
        raise NotImplementedError


class _CurseResolver(BaseResolver, origin='curse'):

    _data: dict

    _json_dump_url = 'https://clientupdate-v6.cursecdn.com/feed/addons/1/v10/'\
                     '{freq}.json.bz2'
    _json_date_url = 'https://clientupdate-v6.cursecdn.com/feed/addons/1/v10/'\
                     '{freq}.json.bz2.txt'

    _freqs = {'hourly', 'daily', 'weekly', 'complete'}

    _re_curse_url = re.compile(r'(?P<id>\d+)-(?P<slug>[a-z_-]+)')

    @classmethod
    def _slug_from_url(cls, url: str) -> str:
        name = URL(url).name
        match = cls._re_curse_url.match(name)
        if match:
            return match.group('slug')
        return name

    async def sync(self):
        async def _sync(freq):
            entry = self.manager.db.query(CacheEntry).get(('curse', freq))
            if not entry or ((entry.date_retrieved + timedelta(seconds=EXPIRY)) <
                             dt.now()):
                async with self.manager.client.get(self._json_date_url
                                                   .format(freq=freq)) as resp:
                    dt_ = dt.fromtimestamp(int(await resp.text()) / 1000)
                if not entry or entry.date_updated != dt_:
                    async with self.manager.client.get(self._json_dump_url
                                                       .format(freq=freq)) as resp:
                        payload = await resp.read()
                    payload = await self.manager.block_in_thread(
                        lambda: bz2.decompress(payload).decode())
                    new_entry = CacheEntry(origin=self.origin,
                                           id=freq,
                                           date_retrieved=dt.now(),
                                           date_updated=dt_,
                                           contents=payload)
                    entry = new_entry.replace(self.manager.db, entry)
            return entry

        data = await self.manager.gather((_sync(f) for f in self._freqs),
                                         show_progress=self.manager.show_progress)
        data = sorted(data, key=lambda e: e.date_updated, reverse=True)
        data = ChainMap(*({str(e['Id']): e
                           for e in c.contents['data'] if e['PackageType'] == 1}
                          for c in data),
                        *({self._slug_from_url(e['WebSiteURL']): e
                           for e in c.contents['data'] if e['PackageType'] == 1}
                          for c in data))
        self._data = data

    async def resolve(self, id_or_slug, *, strategy):
        try:
            proj = self._data[id_or_slug]
        except KeyError:
            # This really shouldn't happen but projects are sometimes missing
            # from the data dumps - maybe there's another dump we're yet to
            # uncover?
            raise self.manager.PkgNonexistent
        file = next(f for f in proj['LatestFiles']
                    if f['Id'] == (proj['DefaultFileId'] if strategy == 'canonical' else
                                   max(f['Id'] for f in proj['LatestFiles']
                                       if f['IsAlternate'] is False)))
        return Pkg(origin='curse', id=proj['Id'], slug=resp.url.name,
                   name=proj['Name'], description=proj['Summary'],
                   url=proj['WebSiteURL'], file_id=file['Id'],
                   download_url=file['DownloadURL'],
                   date_published=file['FileDate'],
                   folders=[PkgFolder(path=self.manager.config.addon_dir/m['Foldername'])
                            for m in file['Modules']],
                   version=file['FileName'],
                   options=PkgOptions(strategy=strategy))

    @classmethod
    def decompose_url(cls, url):
        url = URL(url)
        if url.host in {'wow.curseforge.com', 'www.wowace.com'} and \
                len(url.parts) > 2 and \
                url.parts[1] == 'projects':
            return ('curse', url.parts[2])
        elif url.host == 'mods.curse.com':
            if len(url.parts) > 3 and \
                    url.parts[1:3] == ('addons', 'wow'):
                slug = url.parts[3]
                match = cls._re_curse_url.match(slug)
                if match:
                    slug, = match.groups()
                return ('curse', slug)
            elif len(url.parts) == 3 and \
                    url.parts[1] == 'project':
                return ('curse', url.parts[2])


class _WowiResolver(BaseResolver, origin='wowi'):

    _data: dict

    _json_dump_url = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    _details_api_endpoint = 'https://api.mmoui.com/v3/game/WOW/filedetails/'

    _re_head = re.compile(r'^info')
    _re_tail = re.compile(r'\.html$')

    _re_url = re.compile(r'(?:download|info)(\d+)-.*')

    @classmethod
    def _slugify(cls, url):
        return cls._re_tail.sub('', cls._re_head.sub('', URL(url).name))

    async def sync(self):
        entry = self.manager.db.query(CacheEntry).get(('wowi', 'wowi'))
        if not entry or ((entry.date_retrieved + timedelta(seconds=EXPIRY)) <
                         dt.now()):
            async with self.manager.client.get(self._json_dump_url) as resp:
                data = await resp.read()
            new_entry = CacheEntry(origin='wowi', id='wowi',
                                   date_retrieved=dt.now(), contents=data)
            new_entry.replace(entry, self.manager.db) \
                if entry else new_entry.insert(self.manager.db)

    def load(self):
        data = self.manager.db.query(CacheEntry).get(('wowi', 'wowi')).contents
        self._data = {e['UID']: e for e in data}

    async def resolve(self, id_or_slug, *, strategy):
        f_id = (id_or_slug if id_or_slug.isnumeric() else
                id_or_slug.partition('-')[0])
        try:
            file = self._data[f_id]
        except KeyError:
            raise self.manager.PkgNonexistent
        async with self.manager.client.get(f'{self._details_api_endpoint}'
                                           f'/{f_id}.json') as resp:
            details, = await resp.json()
        return Pkg(origin='wowi', id=file['UID'],
                   slug=self._slugify(file['UIFileInfoURL']),
                   name=file['UIName'], description=details['UIDescription'],
                   url=file['UIFileInfoURL'], file_id=details['UIMD5'],
                   download_url=details['UIDownload'],
                   date_published=details['UIDate'],
                   folders=[PkgFolder(path=self.manager.config.addon_dir/f)
                            for f in file['UIDir']],
                   version=details['UIVersion'],
                   options=PkgOptions(strategy=strategy))

    @classmethod
    def decompose_url(cls, url):
        url = URL(url)
        if url.host in {'wowinterface.com', 'www.wowinterface.com'} and \
                len(url.parts) == 3 and \
                url.parts[1] == 'downloads':
            match = cls._re_url.match(url.name)
            if match:
                return ('wowi', *match.groups())
