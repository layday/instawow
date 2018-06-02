
import asyncio
import bz2
from datetime import datetime as dt, timedelta
import re
import typing as T

from yarl import URL

from .models import CacheEntry, Pkg, PkgFolder, PkgOptions


EXPIRY = 3600


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

    _data: dict

    _json_dump_url = 'https://clientupdate-v6.cursecdn.com/feed/addons/1/v10/'\
                     '{freq}.json.bz2'
    _json_date_url = f'{_json_dump_url}.txt'
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
            entry = self.db.query(CacheEntry).get((self.origin, freq))
            if not entry or ((entry.date_retrieved + timedelta(seconds=EXPIRY)) <
                             dt.now()):
                async with self.wc.get(self._json_date_url
                                           .format(freq=freq)) as resp:
                    dt_ = dt.fromtimestamp(int(await resp.text()) / 1000)
                if not entry or entry.date_updated != dt_:
                    async with self.wc.get(self._json_dump_url
                                               .format(freq=freq)) as resp:
                        payload = await resp.read()
                    payload = await self.block_in_thread(lambda: bz2.decompress(payload)
                                                                    .decode())
                    new_entry = CacheEntry(origin=self.origin, id=freq,
                                           date_retrieved=dt.now(),
                                           date_updated=dt_, contents=payload)
                    entry = self.db.x_replace(new_entry, entry)
            return entry

        data = await self.gather((_sync(f) for f in self._freqs),
                                 desc='Updating Curse cache')
        data = sorted(data, key=lambda e: e.date_updated, reverse=True)
        data = {k: v
                for c in data
                for e in c.contents['data'] if e['PackageType'] == 1
                for k, v in ((str(e['Id']), e),
                             (self._slug_from_url(e['WebSiteURL']), e))}
        self._data = data

    async def resolve(self, id_or_slug: str, *,
                      strategy: str) -> Pkg:
        try:
            proj = self._data[id_or_slug]
        except KeyError:
            # This really shouldn't happen but projects are sometimes missing
            # from the data dumps - maybe there's another dump we're yet to
            # uncover?
            raise self.PkgNonexistent

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
                   version=file['FileName'],
                   options=PkgOptions(strategy=strategy))


class _WowiResolver(BaseResolver,
                    origin='wowi', name='WoWInterface'):

    _data: dict

    _json_dump_url = 'https://api.mmoui.com/v3/game/WOW/filelist.json'
    _details_api_endpoint = 'https://api.mmoui.com/v3/game/WOW/filedetails/'

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
        if not entry or ((entry.date_retrieved + timedelta(seconds=EXPIRY)) <
                         dt.now()):
            async with self.wc.get(self._json_dump_url) as resp:
                data = await resp.read()
            new_entry = CacheEntry(origin=self.origin, id=self.origin,
                                   date_retrieved=dt.now(), contents=data)
            entry = self.db.x_replace(new_entry, entry)

        self._data = {e['UID']: e for e in entry.contents}

    async def resolve(self, id_or_slug: str, *,
                      strategy: str) -> Pkg:
        file_id = id_or_slug.partition('-')[0]
        try:
            file = self._data[file_id]
        except KeyError:
            raise self.PkgNonexistent

        async with self.wc.get(f'{self._details_api_endpoint}/{file_id}.json') \
                as resp:
            details, = await resp.json()
        if file['UIDate'] != details['UIDate']:
            raise self.CacheObsolete

        return Pkg(origin=self.origin,
                   id=file['UID'],
                   slug=f'{file["UID"]}-{file["UIName"]}',
                   name=file['UIName'],
                   description=details['UIDescription'],
                   url=file['UIFileInfoURL'],
                   file_id=details['UIMD5'],
                   download_url=details['UIDownload'],
                   date_published=details['UIDate'],
                   version=details['UIVersion'],
                   options=PkgOptions(strategy=strategy))
