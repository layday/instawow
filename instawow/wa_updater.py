from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, NamedTuple, Optional, Sequence

from loguru import logger
from pydantic import BaseModel, Extra, validator
from yarl import URL

from .config import BaseConfig
from .utils import (ManagerAttrAccessMixin, bucketise, cached_property, dict_chain, gather,
                    run_in_thread as t)

if TYPE_CHECKING:
    from .manager import Manager


metadata_api = URL('https://data.wago.io/api/check/weakauras')
raw_api = URL('https://data.wago.io/api/raw/encoded')


class BuilderConfig(BaseConfig):
    account: str

    class Config:
        env_prefix = 'WAC_'


class AuraEntry(BaseModel):
    id: str
    uid: str
    parent: Optional[str]
    url: URL
    version: int
    semver: Optional[str]
    ignore_wago_update: bool = False

    class Config:
        arbitrary_types_allowed = True
        fields = {'ignore_wago_update': {'alias': 'ignoreWagoUpdate'}}

    @validator('url', pre=True)
    def _convert_url(cls, value: str) -> URL:
        return URL(value)


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


class _OutdatedAuras(NamedTuple):
    slug: str
    existing_auras: List[AuraEntry]
    metadata: ApiMetadata
    import_string: str


class WaCompanionBuilder(ManagerAttrAccessMixin):
    """A WeakAuras Companion port for shellfolk."""

    def __init__(self, manager: Manager, account: Optional[str] = None) -> None:
        self.manager = manager

        self.out_dir = self.config.plugin_dir / __name__
        self.addon_file = self.out_dir / 'WeakAurasCompanion.zip'
        self.account = account

    def ensure_dirs(self) -> WaCompanionBuilder:
        self.out_dir.mkdir(exist_ok=True)
        return self

    @cached_property
    def builder_config(self) -> BuilderConfig:
        return BuilderConfig(account=self.account)

    @staticmethod
    def extract_auras(source: str) -> Dict[str, List[AuraEntry]]:
        from lupa import LuaRuntime     # type: ignore
        lua_eval = LuaRuntime().eval

        table = lua_eval(source[source.find('= ') + 1 :])
        raw_auras = map(dict, table['displays'].values())
        aura_groups = bucketise((AuraEntry(**a) for a in raw_auras if a.get('url')),
                                key=lambda a: a.url.parts[1])
        return aura_groups

    def extract_installed_auras(self) -> Dict[str, List[AuraEntry]]:
        import time

        saved_vars = (self.config.addon_dir.parents[1]
                      / 'WTF/Account' / self.builder_config.account
                      / 'SavedVariables/WeakAuras.lua')

        start = time.perf_counter()
        aura_groups = self.extract_auras(saved_vars.read_text(encoding='utf-8'))
        logger.debug(f'auras extracted in {time.perf_counter() - start}s')
        return aura_groups

    async def get_wago_aura_metadata(self, aura_ids: Sequence[str]) -> List[ApiMetadata]:
        url = metadata_api.with_query(ids=','.join(aura_ids))
        async with self.web_client.get(url) as response:
            metadata = await response.json()

        results = dict_chain(aura_ids, None,
                             ((i.slug, i) for i in map(ApiMetadata.parse_obj, metadata)))
        return list(results.values())

    async def get_wago_aura_import_string(self, aura_id: str) -> str:
        async with self.web_client.get(raw_api.with_query(id=aura_id)) as response:
            return await response.text()

    async def get_outdated_auras(self, aura_groups: Dict[str, List[AuraEntry]]) -> List[_OutdatedAuras]:
        metadata = await self.get_wago_aura_metadata(list(aura_groups))
        outdated = [((s, w), r)
                    for (s, w), r in zip(aura_groups.items(), metadata)
                    if r and r.version > next((a for a in w if not a.parent), w[0]).version]
        import_strings = await gather((self.get_wago_aura_import_string(r.id)
                                       for _, r in outdated), False)
        return [_OutdatedAuras(s, w, r, i) for ((s, w), r), i in zip(outdated, import_strings)]

    def make_addon(self, outdated_auras: Sequence[_OutdatedAuras]) -> None:
        from jinja2 import Environment, FunctionLoader
        from zipfile import ZipFile, ZipInfo

        def loader(filename: str) -> str:
            from importlib.resources import read_text
            from . import wa_templates

            return read_text(wa_templates, filename)

        jinja_env = Environment(trim_blocks=True, lstrip_blocks=True,
                                loader=FunctionLoader(loader))

        with ZipFile(self.ensure_dirs().addon_file, 'w') as file:
            def write_tpl(filename: str, ctx: dict) -> None:
                # We're not using a plain string as the first argument to
                # ``writestr`` 'cause the timestamp is generated dynamically
                # by default making the build unreproducible
                zip_info = ZipInfo(filename=f'WeakAurasCompanion/{filename}')
                file.writestr(zip_info, jinja_env.get_template(filename).render(ctx))

            write_tpl('data.lua',
                      {'was': [(o.metadata.slug,
                                {'name': o.metadata.name,
                                 'author': o.metadata.username,
                                 'encoded': o.import_string,
                                 'wagoVersion': o.metadata.version,
                                 'wagoSemver': o.metadata.version_string,
                                 'versionNote': o.metadata.changelog.text})
                               for o in outdated_auras],
                       'uids': [(a.uid, a.url.parts[1])
                                for o in outdated_auras
                                for a in o.existing_auras],
                       'ids':  [(a.id, a.url.parts[1])
                                for o in outdated_auras
                                for a in o.existing_auras],
                       'stash': []})    # Send to WAC not supported - always empty
            write_tpl('init.lua', {})
            write_tpl('WeakAurasCompanion.toc',
                      {'interface': '11303' if self.config.is_classic else '80300'})

    async def build(self) -> None:
        aura_groups = {k: v
                       for k, v in (await t(self.extract_installed_auras)()).items()
                       if not any(i.ignore_wago_update for i in v)}
        outdated_auras = aura_groups and await self.get_outdated_auras(aura_groups)
        await t(self.make_addon)(outdated_auras)

    def checksum(self) -> str:
        from hashlib import sha256

        return sha256(self.addon_file.read_bytes()).hexdigest()
