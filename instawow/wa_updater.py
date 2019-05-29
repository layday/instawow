
from __future__ import annotations

__all__ = ('WaCompanionBuilder',)

import asyncio
from functools import partial, reduce
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from loguru import logger
from pydantic import BaseModel, Extra, validator
from yarl import URL

from .utils import ManagerAttrAccessMixin, bucketise

if TYPE_CHECKING:
    from luaparser import astnodes as lua_nodes
    from .manager import Manager


metadata_api = URL('https://data.wago.io/api/check/weakauras')
raw_api = URL('https://data.wago.io/api/raw/encoded')

_EMPTY_URL = URL()


class AuraURLInvalid(Exception):
    pass


class AuraEntry(BaseModel):

    id: str
    uid: str
    parent: Optional[str]
    url: URL = _EMPTY_URL
    version: int
    semver: Optional[str]
    ignore_wago_update: bool = False

    class Config:
        arbitrary_types_allowed = True
        fields = {'ignore_wago_update' : {'alias': 'ignoreWagoUpdate'}}

    @validator('url', always=True, pre=True)
    def __prep_url(cls, value: Any) -> Any:
        if value == _EMPTY_URL:
            raise AuraURLInvalid
        return value

    @validator('id', 'uid', 'parent', 'url', 'semver', pre=True)
    def __convert_str(cls, value: lua_nodes.String) -> str:
        return value.s

    @validator('version', pre=True)
    def __convert_int(cls, value: lua_nodes.Number) -> int:
        return value.n

    @validator('ignore_wago_update', pre=True)
    def __convert_bool(cls, value: Union[lua_nodes.TrueExpr, lua_nodes.FalseExpr]
                       ) -> bool:
        return value.display_name == 'True'

    @validator('url', pre=True)
    def __postp_url(cls, value: str) -> URL:
        url = URL(value)
        if url.host != 'wago.io':
            logger.info(f'discarding aura with URL: {url}')
            raise AuraURLInvalid
        return url

    @classmethod
    def from_lua_ast(cls, tree: lua_nodes.Field) -> Optional[AuraEntry]:
        try:
            return cls(**{f.key.s: f.value for f in tree.value.fields})
        # The URL validators raise an exception not derived from ValueError
        # so that they won't be wrapped by Pydantic and we can catch them here
        except AuraURLInvalid:
            return None


class ApiMetadata__Changelog(BaseModel):

    format: Optional[str]
    text: str = ''

    class Config:
        extra = Extra.forbid


class ApiMetadata(BaseModel):

    id: str
    name: str
    slug: str
    url: str
    created: str
    modified: str
    game: str
    fork_of: Optional[str]
    username: str
    version: int
    version_string: str
    changelog: ApiMetadata__Changelog
    region_type: Optional[str]

    class Config:
        extra = Extra.forbid
        fields = {'id': {'alias': '_id'},
                  'fork_of': {'alias': 'forkOf'},
                  'version_string': {'alias': 'versionString'},
                  'region_type': {'alias': 'regionType'}}


_T_Outdated = List[Tuple[str, List[AuraEntry], ApiMetadata, str]]


class WaCompanionBuilder(ManagerAttrAccessMixin):
    """A WeakAuras Companion port for shellfolk."""

    def __init__(self, manager: Manager) -> None:
        self.manager = manager
        self.builder_dir = self.manager.config.plugin_dir / __name__
        self.file_out = self.builder_dir / 'WeakAurasCompanion.zip'

    @staticmethod
    def extract_auras_from_lua(source: str) -> Dict[str, List[AuraEntry]]:
        from luaparser import ast as lua_ast

        lua_tree = lua_ast.walk(lua_ast.parse(source))
        aura_table = next(i for i in lua_tree
                          if reduce(lambda p, n: getattr(p, n, None),
                                    [i, 'key', 's']) == 'displays').value.fields
        auras = filter(None, map(AuraEntry.from_lua_ast, aura_table))
        aura_groups = bucketise(auras, key=lambda a: a.url.parts[1])
        aura_groups = {k: v for k, v in aura_groups.items()
                       if not any(i for i in v if i.ignore_wago_update)}
        return aura_groups

    async def get_wago_aura_metadata(self, aura_ids: Sequence[str]
                                     ) -> List[ApiMetadata]:
        url = metadata_api.with_query({'ids': ','.join(aura_ids)})
        async with self.client.get()\
                              .get(url) as response:
            metadata = await response.json()

        results = dict.fromkeys(aura_ids)
        for item in (ApiMetadata(**i) for i in metadata):
            if item.slug in results:
                results[item.slug] = item
        return list(results.values())

    async def get_wago_aura(self, aura_id: str) -> str:
        url = raw_api.with_query({'id': aura_id})
        async with self.client.get()\
                              .get(url) as response:
            return await response.text()

    async def get_outdated(self) -> _T_Outdated:
        import time

        def extract_auras_from_lua():
            saved_vars = Path.glob(self.config.addon_dir.parents[1],
                                   'WTF/Account/*/SavedVariables/WeakAuras.lua')
            auras = (self.extract_auras_from_lua(f.read_text(encoding='utf-8'))
                     for f in saved_vars)
            return reduce(lambda p, n: {**p, **n}, auras)

        start = time.perf_counter()
        aura_groups = await self.loop.run_in_executor(None,
                                                      extract_auras_from_lua)
        logger.debug(f'auras extracted in {time.perf_counter() - start}s')
        if not aura_groups:
            return []

        aura_metadata = await self.get_wago_aura_metadata(list(aura_groups))
        auras_with_metadata = filter(lambda v: v[1],
                                     zip(aura_groups.items(), aura_metadata))
        outdated_auras = [((s, w), r) for (s, w), r in auras_with_metadata
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

        tpl_dir = Path(__file__).parent / 'wa_templates'
        jinja_env = Environment(loader=FileSystemLoader(str(tpl_dir)),
                                trim_blocks=True, lstrip_blocks=True)

        with ZipFile(self.file_out, 'w') as addon_zip:
            def write_tpl(tpl: str, ctx: dict) -> None:
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
