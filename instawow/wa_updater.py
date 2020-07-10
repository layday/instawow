from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    NamedTuple,
    Optional as O,
    Sequence,
    Tuple,
    Type,
)

from loguru import logger
from pydantic import BaseModel, Extra, ValidationError, validator
from yarl import URL

from .config import BaseConfig
from .utils import ManagerAttrAccessMixin, bucketise, dict_chain, gather, run_in_thread as t

if TYPE_CHECKING:
    from .manager import Manager


import_api = URL('https://data.wago.io/api/raw/encoded')


class BuilderConfig(BaseConfig):
    account: str

    class Config:
        env_prefix = 'WAC_'


class WaConfigError(Exception):
    pass


class WeakAura(BaseModel):
    id: str
    uid: str
    parent: O[str]
    url: URL
    version: int
    semver: O[str]
    ignore_wago_update: bool = False

    class Config:
        arbitrary_types_allowed = True
        fields = {'ignore_wago_update': 'ignoreWagoUpdate'}

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
    uid = ''

    class Config:
        arbitrary_types_allowed = True
        fields = {'id': 'Name'}


class Plateroos(WeakAuras):
    entries: Dict[str, List[Plateroo]]

    class Meta:
        model = Plateroo
        filename = 'Plater.lua'
        table_prefix = 'PlaterDB'
        api = URL('https://data.wago.io/api/check/plater')

    @classmethod
    def from_lua_table(cls, lua_table: Dict[Any, Any]) -> Plateroos:
        auras = (
            cls.Meta.model.parse_obj(a)
            for p in lua_table['profiles'].values()
            for n, v in p.items()
            if n in ('script_data', 'hook_data')
            for a in v
            if a.get('url')
        )
        return cls(entries=bucketise(auras, key=lambda a: a.url.parts[1]))


class _ApiChangelog(BaseModel):
    format: O[str]
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
    fork_of: O[str]
    username: str
    version: int
    version_string: str
    changelog: _ApiChangelog
    region_type: O[str]

    class Config:
        extra = Extra.forbid
        fields = {
            'id': '_id',
            'fork_of': 'forkOf',
            'version_string': 'versionString',
            'region_type': 'regionType',
        }


class RemoteAura(NamedTuple):
    slug: str
    existing_auras: List[WeakAura]
    metadata: ApiMetadata
    import_string: str


class WaCompanionBuilder(ManagerAttrAccessMixin):
    """A WeakAuras Companion port for shellfolk."""

    def __init__(self, manager: Manager, account: O[str] = None) -> None:
        self.manager = manager
        self.addon_file = self.config.plugin_dir / __name__ / 'WeakAurasCompanion.zip'
        self.account = account

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

    def extract_installed_auras(self) -> Iterable[WeakAuras]:
        import time

        try:
            builder_config = BuilderConfig(account=self.account)
        except ValidationError as error:
            raise WaConfigError from error

        saved_vars = (
            self.config.addon_dir.parents[1]
            / 'WTF'
            / 'Account'
            / builder_config.account
            / 'SavedVariables'
        )
        for model in WeakAuras, Plateroos:
            file = saved_vars / model.Meta.filename
            if not file.exists():
                logger.info(f'{file} not found')
            else:
                start = time.perf_counter()
                aura_groups = self.extract_auras(
                    model, file.read_text(encoding='utf-8-sig', errors='replace')
                )
                logger.debug(f'auras extracted in {time.perf_counter() - start}s')
                yield aura_groups

    async def get_wago_metadata(self, aura_groups: WeakAuras) -> List[ApiMetadata]:
        aura_ids = list(aura_groups.entries)
        url = aura_groups.Meta.api.with_query(ids=','.join(aura_ids))
        async with self.web_client.get(url) as response:
            metadata = await response.json()

        results = dict_chain(
            aura_ids, None, ((i.slug, i) for i in map(ApiMetadata.parse_obj, metadata))
        )
        return list(results.values())

    async def get_wago_import_string(self, aura_id: str) -> str:
        async with self.web_client.get(import_api.with_query(id=aura_id)) as response:
            return await response.text()

    async def get_remote_auras(
        self, aura_groups: WeakAuras
    ) -> Tuple[Type[WeakAuras], List[RemoteAura]]:
        metadata = await self.get_wago_metadata(aura_groups)
        import_strings = await gather((self.get_wago_import_string(m.id) for m in metadata), False)
        return (
            aura_groups.__class__,
            [
                RemoteAura(slug=s, existing_auras=e, metadata=m, import_string=i)
                for (s, e), m, i in zip(aura_groups.entries.items(), metadata, import_strings)
            ],
        )

    def make_addon(self, auras: Sequence[Tuple[Type[WeakAuras], Sequence[RemoteAura]]]) -> None:
        from zipfile import ZipFile, ZipInfo

        from jinja2 import Environment, FunctionLoader

        def loader(filename: str) -> str:
            from importlib.resources import read_text

            from . import wa_templates

            return read_text(wa_templates, filename)

        jinja_env = Environment(
            trim_blocks=True, lstrip_blocks=True, loader=FunctionLoader(loader)
        )
        aura_dict = dict_chain((WeakAuras, Plateroos), [], auras)

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
                            o.metadata.slug,
                            {
                                'name': o.metadata.name,
                                'author': o.metadata.username,
                                'encoded': o.import_string,
                                'wagoVersion': o.metadata.version,
                                'wagoSemver': o.metadata.version_string,
                                'versionNote': o.metadata.changelog.text,
                            },
                        )
                        for o in aura_dict[WeakAuras]
                    ],
                    # Maps internal UIDs of top-level auras to IDs or slugs on Wago
                    'weakaura_uids': [
                        (a.uid, a.url.parts[1])
                        for o in aura_dict[WeakAuras]
                        for a in (
                            next(
                                (i for i in o.existing_auras if not i.parent), o.existing_auras[0]
                            ),
                        )
                    ],
                    # Maps local names to IDs or slugs on Wago
                    'weakaura_ids': [
                        (a.id, a.url.parts[1])
                        for o in aura_dict[WeakAuras]
                        for a in o.existing_auras
                    ],
                    'plateroos': [
                        (
                            o.metadata.slug,
                            {
                                'name': o.metadata.name,
                                'author': o.metadata.username,
                                'encoded': o.import_string,
                                'wagoVersion': o.metadata.version,
                                'wagoSemver': o.metadata.version_string,
                                'versionNote': o.metadata.changelog.text,
                            },
                        )
                        for o in aura_dict[Plateroos]
                    ],
                    'plater_ids': [
                        (a.id, a.url.parts[1])
                        for o in aura_dict[Plateroos]
                        for a in o.existing_auras
                    ],
                },
            )
            write_tpl('init.lua', {})
            write_tpl(
                'WeakAurasCompanion.toc',
                {'interface': '11303' if self.config.is_classic else '80300'},
            )

    async def build(self) -> None:
        aura_groups = await t(self.extract_installed_auras)()
        aura_groups = [
            g.__class__(
                entries={
                    k: v for k, v in g.entries.items() if not any(i.ignore_wago_update for i in v)
                }
            )
            for g in aura_groups
        ]
        remote_auras = await gather(self.get_remote_auras(g) for g in aura_groups)
        await t(self.make_addon)(remote_auras)

    def checksum(self) -> str:
        from hashlib import sha256

        return sha256(self.addon_file.read_bytes()).hexdigest()
