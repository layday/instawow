
from __future__ import annotations

import asyncio
from functools import partial, reduce
from pathlib import Path
import time
import typing as T

import logbook
import pydantic
from yarl import URL

from .manager import Manager
from .utils import ManagerAttrAccessMixin

if T.TYPE_CHECKING:
    from luaparser import astnodes as lua_nodes


__all__ = ('WaCompanionBuilder',)


logger = logbook.Logger(__name__)

metadata_api = URL('https://data.wago.io/api/check/weakauras')
raw_api = URL('https://data.wago.io/api/raw/encoded')


def bucketise(iterable: T.Iterable, key=T.Callable[[T.Any], T.Any]) -> dict:
    from collections import defaultdict

    bucket = defaultdict(list)
    for value in iterable:
        bucket[key(value)].append(value)
    return dict(bucket)


class AuraHasNoURL(Exception):
    pass


class AuraURLNotWago(Exception):
    pass


class AuraEntry(pydantic.BaseModel):

    id: str
    uid: str
    parent: T.Optional[str]
    url: T.Optional[URL]
    version: int
    semver: T.Optional[str]
    ignore_wago_update: bool = pydantic.Schema(False, alias='ignoreWagoUpdate')

    @pydantic.validator('url', always=True, pre=True)
    def __prep_url(cls, value: T.Any) -> T.Any:
        if value is None:
            raise AuraHasNoURL
        return value

    @pydantic.validator('id', 'uid', 'parent', 'url', 'semver', pre=True)
    def __convert_str(cls, value: lua_nodes.String) -> str:
        return value.s

    @pydantic.validator('version', pre=True)
    def __convert_int(cls, value: lua_nodes.Number) -> int:
        return value.n

    @pydantic.validator('ignore_wago_update', pre=True)
    def __convert_bool(cls, value: T.Union[lua_nodes.TrueExpr, lua_nodes.FalseExpr]
                       ) -> bool:
        return value.display_name == 'True'

    @pydantic.validator('url', pre=True)
    def __postp_url(cls, value: str) -> URL:
        url = URL(value)
        if url.host != 'wago.io':
            raise AuraURLNotWago
        return url

    @classmethod
    def from_lua_ast(cls, tree: lua_nodes.Field) -> T.Optional[AuraEntry]:
        try:
            return cls(**{f.key.s: f.value for f in tree.value.fields})
        except (AuraHasNoURL, AuraURLNotWago):
            return

    class Config:
        arbitrary_types_allowed = True


class ApiMetadata__Changelog(pydantic.BaseModel):

    format: T.Optional[str]
    text: str = ''


class ApiMetadata(pydantic.BaseModel):

    id: str = pydantic.Schema(..., alias='_id')     # Pydantic won't accept underscored attrs
    name: str
    slug: str
    url: str
    created: str
    modified: str
    username: str
    version: int
    version_string: str = pydantic.Schema(..., alias='versionString')
    changelog: ApiMetadata__Changelog


_T_Outdated = T.List[T.Tuple[str, T.List[AuraEntry], ApiMetadata, str]]


class WaCompanionBuilder(ManagerAttrAccessMixin):
    """A WeakAuras Companion port for shellfolk."""

    def __init__(self, manager: Manager) -> None:
        self.manager = manager
        self.builder_dir = self.manager.config.plugin_dir/__name__
        self.file_out = self.builder_dir/'WeakAurasCompanion.zip'

    @staticmethod
    def extract_auras_from_lua(sources: T.Iterator[str]
                               ) -> T.Dict[str, T.List[AuraEntry]]:
        def extract(source):
            from luaparser import ast as lua_ast

            auras = next(i for i in lua_ast.walk(lua_ast.parse(source))
                         if reduce(lambda p, n: getattr(p, n, None),
                                   [i, 'key', 's']) == 'displays').value.fields
            auras = filter(None, map(AuraEntry.from_lua_ast, auras))
            auras = bucketise(auras, key=lambda a: a.url.parts[1])
            auras = {k: v for k, v in auras.items()
                     if not any(i for i in v if i.ignore_wago_update)}
            return auras

        return reduce(lambda p, n: {**p, **n}, (extract(s) for s in sources))

    async def get_wago_aura_metadata(self, aura_ids: T.List[str]
                                     ) -> T.List[T.Optional[ApiMetadata]]:
        url = metadata_api.with_query({'ids': ','.join(aura_ids)})
        async with self.client.get()\
                              .get(url) as response:
            metadata = await response.json()

        results = dict.fromkeys(aura_ids)
        for item in (ApiMetadata(**i) for i in metadata):
            results[item.slug] = item
        return list(results.values())

    async def get_wago_aura(self, aura_id: str) -> str:
        url = raw_api.with_query({'id': aura_id})
        async with self.client.get()\
                              .get(url) as response:
            return await response.text()

    async def get_outdated(self) -> _T_Outdated:
        def extract_auras_from_lua():
            saved_vars = self.config.addon_dir.parents[1]
            saved_vars = saved_vars.glob('WTF/Account/*/'
                                         'SavedVariables/WeakAuras.lua')
            return self.extract_auras_from_lua(f.read_text(encoding='utf-8')
                                               for f in saved_vars)

        start = time.perf_counter()
        aura_groups = await self.loop.run_in_executor(None,
                                                      extract_auras_from_lua)
        logger.debug(f'Auras extracted in {time.perf_counter() - start}s')
        if not aura_groups:
            return []

        outdated_auras = zip(aura_groups.items(),
                             await self.get_wago_aura_metadata(list(aura_groups)))
        outdated_auras = filter(lambda v: v[1], outdated_auras)
        outdated_auras = [((s, w), r) for (s, w), r in outdated_auras
                          if r.version > next((a for a in w if not a.parent),
                                              w[0]).version]
        if not outdated_auras:
            return []

        new_auras = await asyncio.gather(*(self.get_wago_aura(r.slug)
                                           for _, r in outdated_auras))
        return [(s, w, r, p)
                for ((s, w), r), p in zip(outdated_auras, new_auras)]

    def make_addon(self, outdated: _T_Outdated) -> None:
        from jinja2 import Environment, FileSystemLoader
        from zipfile import ZipFile, ZipInfo

        jinja_env = Environment(loader=FileSystemLoader(str(Path(__file__).parent/'wa_templates')),
                                trim_blocks=True, lstrip_blocks=True)

        with ZipFile(self.file_out, 'w') as addon_zip:
            def write_tpl(tpl, ctx):
                # Not using a plain string as the first argument to ``writestr``
                # 'cause the timestamp is set dynamically by default, which
                # renders the build rather - shall we say - unreproducible
                zip_info = ZipInfo(filename=f'WeakAurasCompanion/{tpl}')
                addon_zip.writestr(zip_info,
                                   jinja_env.get_template(tpl).render(**ctx))

            write_tpl('data.lua',
                      {'was': [(m.slug,
                                {'name': m.name,
                                 'author': m.username,
                                 'encoded': p,
                                 'wagoVersion': m.version,
                                 'wagoSemver': m.version_string,
                                 'versionNote': m.changelog.text})
                               for _, _, m, p, in outdated],
                       'uids': [(a.uid, a.url.parts[1])
                                for _, w, _, _ in outdated
                                for a in w],
                       'ids':  [(a.id, a.url.parts[1])
                                for _, w, _, _ in outdated
                                for a in w],
                       'stash': []})    # Send to WAC not supported - always empty
            write_tpl('init.lua', {})
            write_tpl('WeakAurasCompanion.toc', {})

    async def build(self) -> None:
        await self.loop.run_in_executor(None, lambda: self.builder_dir.mkdir(exist_ok=True))
        make_addon = partial(self.make_addon, await self.get_outdated())
        await self.loop.run_in_executor(None, make_addon)

    def checksum(self) -> str:
        from hashlib import sha256
        return sha256(self.file_out.read_bytes()).hexdigest()
