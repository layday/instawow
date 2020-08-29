from __future__ import annotations

from itertools import chain
from typing import TYPE_CHECKING, Any, Dict, Iterator, List, Optional as O, Sequence, Tuple, Type

from loguru import logger
from pydantic import BaseModel, Field, validator
from yarl import URL

from .config import BaseConfig, Config as GlobalConfig
from .utils import bucketise, chain_dict, gather, iter_in_thread as iit, run_in_thread as t

if TYPE_CHECKING:
    from pathlib import Path

    from .manager import Manager

    ImportString = str
    RemoteAura = Tuple[List['WeakAura'], 'WagoResponse', ImportString]


import_api = URL('https://data.wago.io/api/raw/encoded')


class BuilderConfig(BaseConfig):
    account: str
    api_key: O[str]

    class Config:  # type: ignore
        env_prefix = 'WAC_'

    def get_saved_vars(self, global_config: GlobalConfig) -> Path:
        root_for_flavour = global_config.addon_dir.parents[1]
        return root_for_flavour / 'WTF' / 'Account' / self.account / 'SavedVariables'


class WeakAura(BaseModel):
    id: str
    uid: str
    parent: O[str]
    url: URL
    version: int

    class Config:
        arbitrary_types_allowed = True

    @validator('url', pre=True)
    def _convert_url(cls, value: str) -> URL:
        return URL(value)


class WeakAuras(BaseModel):
    entries: Dict[str, List[WeakAura]]

    class Config:
        arbitrary_types_allowed = True

    class Meta:
        model = WeakAura
        filename = 'WeakAuras.lua'
        table_prefix = 'WeakAurasSaved'
        api = URL('https://data.wago.io/api/check/weakauras')

    @classmethod
    def from_lua_table(cls, lua_table: Dict[Any, Any]) -> WeakAuras:
        auras = (
            cls.Meta.model.parse_obj(a) for a in lua_table['displays'].values() if a.get('url')
        )
        return cls(entries=bucketise(auras, key=lambda a: a.url.parts[1]))


class Plateroo(WeakAura):
    id: str = Field(alias='Name')
    uid = ''


class Plateroos(WeakAuras):
    class Meta:  # type: ignore
        model = Plateroo
        filename = 'Plater.lua'
        table_prefix = 'PlaterDB'
        api = URL('https://data.wago.io/api/check/plater')

    @classmethod
    def from_lua_table(cls, lua_table: Dict[Any, Any]) -> Plateroos:
        auras = (
            cls.Meta.model.parse_obj(a)
            for n, p in lua_table['profiles'].items()
            for a in chain(
                ({**p, 'Name': f'__profile_{n}__'},),
                (i for n, v in p.items() if n in {'script_data', 'hook_data'} for i in v),
            )
            if a.get('url')
        )
        return cls(entries={a.url.parts[1]: [a] for a in auras})


class _WagoChangelog(BaseModel):
    format: O[str]
    text: str = ''


class WagoResponse(BaseModel):
    id: str = Field(alias='_id')
    name: str  # +
    slug: str  # +
    url: str
    created: str
    modified: str
    game: str
    fork_of: O[str] = Field(alias='forkOf')
    username: str  # +
    version: int  # +
    version_string: str = Field(alias='versionString')  # +
    changelog: _WagoChangelog  # +
    region_type: O[str] = Field(alias='regionType')


class WaCompanionBuilder:
    """A WeakAuras Companion port for shellfolk."""

    def __init__(self, manager: Manager, builder_config: BuilderConfig) -> None:
        self.manager = manager
        self.addon_file = self.manager.config.plugin_dir / __name__ / 'WeakAurasCompanion.zip'
        self.builder_config = builder_config

    @staticmethod
    def extract_auras(model: Type[WeakAuras], source: str) -> WeakAuras:
        import re

        from slpp import SLPP

        class WaParser(SLPP):
            def decode(self, text: str) -> Any:
                text = re.sub(rf'^\s*{model.Meta.table_prefix} = ', '', text)
                text = re.sub(r' -- \[\d+\]$', '', text, flags=re.M)
                self.text = text
                self.at, self.ch, self.depth = 0, '', 0
                self.len = len(text)
                self.next_chr()
                return self.value()  # type: ignore

        table = WaParser().decode(source)
        return model.from_lua_table(table)

    def extract_installed_auras(self) -> Iterator[WeakAuras]:
        import time

        saved_vars = self.builder_config.get_saved_vars(self.manager.config)
        for model in WeakAuras, Plateroos:
            file = saved_vars / model.Meta.filename
            if not file.exists():
                logger.info(f'{file} not found')
            else:
                start = time.perf_counter()
                aura_groups = self.extract_auras(
                    model, file.read_text(encoding='utf-8-sig', errors='replace')
                )
                logger.debug(f'{model.__name__} extracted in {time.perf_counter() - start}s')
                yield aura_groups

    async def get_wago_metadata(self, aura_groups: WeakAuras) -> List[WagoResponse]:
        aura_ids = list(aura_groups.entries)
        url = aura_groups.Meta.api.with_query(ids=','.join(aura_ids))
        async with self.manager.web_client.get(
            url, headers={'api-key': self.builder_config.api_key or ''}
        ) as response:
            metadata = await response.json()

        results = chain_dict(
            aura_ids, None, ((i.slug, i) for i in map(WagoResponse.parse_obj, metadata))
        )
        return list(results.values())

    async def get_wago_import_string(self, aura_id: str) -> str:
        async with self.manager.web_client.get(
            import_api.with_query(id=aura_id),
            headers={'api-key': self.builder_config.api_key or ''},
        ) as response:
            return await response.text()

    async def get_remote_auras(
        self, aura_groups: WeakAuras
    ) -> Tuple[Type[WeakAuras], List[RemoteAura]]:
        if not aura_groups.entries:
            return (aura_groups.__class__, [])

        metadata = await self.get_wago_metadata(aura_groups)
        import_strings = await gather((self.get_wago_import_string(m.id) for m in metadata), False)
        return (
            aura_groups.__class__,
            list(zip(aura_groups.entries.values(), metadata, import_strings)),
        )

    def make_addon(self, auras: Sequence[Tuple[Type[WeakAuras], Sequence[RemoteAura]]]) -> None:
        from functools import partial
        from importlib.resources import read_text
        from zipfile import ZipFile, ZipInfo

        from jinja2 import Environment, FunctionLoader

        from . import wa_templates

        jinja_env = Environment(
            trim_blocks=True,
            lstrip_blocks=True,
            loader=FunctionLoader(partial(read_text, wa_templates)),
        )
        aura_dict = chain_dict((WeakAuras, Plateroos), [], auras)

        self.addon_file.parent.mkdir(exist_ok=True)
        with ZipFile(self.addon_file, 'w') as file:

            def write_tpl(filename: str, ctx: Dict[str, Any]) -> None:
                # We're not using a plain string as the first argument to
                # ``writestr`` 'cause then the timestamp is generated dynamically
                # making the build unreproducible
                zip_info = ZipInfo(filename=f'WeakAurasCompanion/{filename}')
                file.writestr(zip_info, jinja_env.get_template(filename).render(ctx))

            write_tpl(
                'data.lua',
                {
                    'weakauras': [
                        (
                            metadata.slug,
                            {
                                'name': metadata.name,
                                'author': metadata.username,
                                'encoded': import_string,
                                'wagoVersion': metadata.version,
                                'wagoSemver': metadata.version_string,
                                'versionNote': metadata.changelog.text,
                            },
                        )
                        for _, metadata, import_string in aura_dict[WeakAuras]
                    ],
                    # Maps internal UIDs of top-level auras to IDs or slugs on Wago
                    'weakaura_uids': [
                        (a.uid, a.url.parts[1])
                        for existing_auras, _, _ in aura_dict[WeakAuras]
                        for a in (
                            next((i for i in existing_auras if not i.parent), existing_auras[0]),
                        )
                    ],
                    # Maps local names to IDs or slugs on Wago
                    'weakaura_ids': [
                        (a.id, a.url.parts[1])
                        for existing_auras, _, _ in aura_dict[WeakAuras]
                        for a in existing_auras
                    ],
                    'plateroos': [
                        (
                            metadata.slug,
                            {
                                'name': metadata.name,
                                'author': metadata.username,
                                'encoded': import_string,
                                'wagoVersion': metadata.version,
                                'wagoSemver': metadata.version_string,
                                'versionNote': metadata.changelog.text,
                            },
                        )
                        for _, metadata, import_string in aura_dict[Plateroos]
                    ],
                    'plater_ids': [
                        (a.id, a.url.parts[1])
                        for existing_auras, _, _ in aura_dict[Plateroos]
                        for a in existing_auras
                    ],
                },
            )
            write_tpl('init.lua', {})
            write_tpl(
                'WeakAurasCompanion.toc',
                {'interface': '11305' if self.manager.config.is_classic else '80300'},
            )

    async def build(self) -> None:
        installed_auras = iit(self.extract_installed_auras())
        remote_auras = await gather(
            [self.get_remote_auras(g) async for g in installed_auras],
            False,
        )
        await t(self.make_addon)(remote_auras)

    def checksum(self) -> str:
        from hashlib import sha256

        return sha256(self.addon_file.read_bytes()).hexdigest()
