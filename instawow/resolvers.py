
import bz2
from collections import ChainMap
from datetime import datetime as dt, timedelta
import re
import typing as T

from yarl import URL

from .models import CacheEntry, Pkg, PkgFolder, PkgOptions


EXPIRY = 3600


class BaseResolver:

    __members__ = {}

    def __init__(self, *, manager: 'Manager'):
        self.manager = manager
        self.synced = False

    def __init_subclass__(cls, origin: str):
        cls.__members__[origin] = cls
        cls.origin = origin

        orig_sync = cls.sync
        async def _sync(self) -> None:
            if not self.synced:
                await orig_sync(self)
                self.synced = True
        cls.sync = _sync

    @classmethod
    def decompose_url(cls, url: str) -> T.Optional[T.Tuple[str, str]]:
        """Break a URL down into its component `origin` and `id`."""

    async def sync(self) -> None:
        """Serves as a deferred, asynchronous `__init__`.  Do any
        preprocessing here if necessary, including writing to the cache.
        """
    async def resolve(self, id_or_slug: str, *,
                      strategy: str) -> Pkg:
        """Turn an ID or slug into a `models.Pkg`."""
        raise NotImplementedError


class _CurseResolver(BaseResolver,
                     origin='curse'):

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

    async def sync(self) -> None:
        async def _sync(freq):
            entry = self.manager.db.query(CacheEntry).get((self.origin, freq))
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
                                         show_progress=self.manager.show_progress,
                                         label='Updating Curse cache')
        data = sorted(data, key=lambda e: e.date_updated, reverse=True)
        data = ChainMap(*({str(e['Id']): e
                           for e in c.contents['data'] if e['PackageType'] == 1}
                          for c in data),
                        *({self._slug_from_url(e['WebSiteURL']): e
                           for e in c.contents['data'] if e['PackageType'] == 1}
                          for c in data))
        self._data = data

    async def resolve(self,
                      id_or_slug: str,
                      *,
                      strategy: str) -> Pkg:
        try:
            proj = self._data[id_or_slug]
        except KeyError:
            # This really shouldn't happen but projects are sometimes missing
            # from the data dumps - maybe there's another dump we're yet to
            # uncover?
            raise self.manager.PkgNonexistent

        if strategy == 'canonical':
            file_id = proj['DefaultFileId']
        elif strategy == 'latest':
            file_id = max(f['Id'] for f in proj['LatestFiles']
                          if f['IsAlternate'] is False)
        file = next(f for f in proj['LatestFiles'] if f['Id'] == file_id)

        return Pkg(origin=self.origin,
                   id=proj['Id'],
                   slug=self._slug_from_url(proj['WebSiteURL']),
                   name=proj['Name'],
                   description=proj['Summary'],
                   url=proj['WebSiteURL'],
                   file_id=file['Id'],
                   download_url=file['DownloadURL'],
                   date_published=file['FileDate'],
                   folders=[PkgFolder(path=self.manager.config.addon_dir/m['Foldername'])
                            for m in file['Modules']],
                   version=file['FileName'],
                   options=PkgOptions(strategy=strategy))


class _WowiResolver(BaseResolver,
                    origin='wowi'):

    _data: dict

    _json_dump_url = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    _details_api_endpoint = 'https://api.mmoui.com/v3/game/WOW/filedetails/'

    _re_head = re.compile(r'^info')
    _re_tail = re.compile(r'\.html$')

    _re_addon_url = re.compile(r'(?:download|info)(\d+)')

    @classmethod
    def _slugify(cls, url: str) -> str:
        return cls._re_tail.sub('', cls._re_head.sub('', URL(url).name))

    @classmethod
    def decompose_url(cls, url: str) -> T.Optional[T.Tuple[str, str]]:
        url = URL(url)
        if url.host in {'wowinterface.com', 'www.wowinterface.com'} \
                and len(url.parts) == 3 \
                and url.parts[1] == 'downloads':
            match = cls._re_addon_url.match(url.name)
            if match:
                return (cls.origin, match.group(1))

    async def sync(self) -> None:
        entry = self.manager.db.query(CacheEntry).get((self.origin, self.origin))
        if not entry or ((entry.date_retrieved + timedelta(seconds=EXPIRY)) <
                         dt.now()):
            async with self.manager.client.get(self._json_dump_url) as resp:
                data = await resp.read()
            new_entry = CacheEntry(origin=self.origin, id=self.origin,
                                   date_retrieved=dt.now(), contents=data)
            entry = new_entry.replace(self.manager.db, entry)

        self._data = {e['UID']: e for e in entry.contents}

    async def resolve(self,
                      id_or_slug: str,
                      *,
                      strategy: str) -> Pkg:
        file_id = id_or_slug if id_or_slug.isnumeric() else \
            id_or_slug.partition('-')[0]
        try:
            file = self._data[file_id]
        except KeyError:
            raise self.manager.PkgNonexistent

        async with self.manager.client.get(f'{self._details_api_endpoint}'
                                           f'/{file_id}.json') as resp:
            details, = await resp.json()
        if file['UIDate'] != details['UIDate']:
            raise self.manager.CacheObsolete

        return Pkg(origin=self.origin,
                   id=file['UID'],
                   slug=self._slugify(file['UIFileInfoURL']),
                   name=file['UIName'],
                   description=details['UIDescription'],
                   url=file['UIFileInfoURL'],
                   file_id=details['UIMD5'],
                   download_url=details['UIDownload'],
                   date_published=details['UIDate'],
                   folders=[PkgFolder(path=self.manager.config.addon_dir/f)
                            for f in file['UIDir']],
                   version=details['UIVersion'],
                   options=PkgOptions(strategy=strategy))
