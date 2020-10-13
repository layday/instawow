from __future__ import annotations

from functools import partial, reduce
from itertools import chain, product
import time
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Dict,
    Generic,
    Iterable,
    Iterator,
    List,
    Optional as O,
    Sequence,
    Tuple,
    Type,
    TypeVar,
)

from loguru import logger
from pydantic import BaseModel, Field, validator
from pydantic.generics import GenericModel
from typing_extensions import Literal, TypedDict
from yarl import URL

from .config import BaseConfig
from .utils import bucketise, chain_dict, gather, run_in_thread as t, shasum

if TYPE_CHECKING:
    from .manager import Manager

    ImportString = str
    RemoteAuras = List[Tuple[List[WeakAura], WagoApiResponse, ImportString]]


class BuilderConfig(BaseConfig):
    wago_api_key: O[str]

    class Config:  # type: ignore
        env_prefix = 'INSTAWOW_'


WeakAuraT = TypeVar('WeakAuraT', bound='WeakAura')

import_api_url = URL('https://data.wago.io/api/raw/encoded')


class Auras(GenericModel, Generic[WeakAuraT]):
    _filename: ClassVar[str]
    _api_url: ClassVar[URL]

    __root__: Dict[str, List[WeakAuraT]]

    class Config:
        arbitrary_types_allowed = True
        json_encoders = {
            URL: str,
        }

    @classmethod
    def from_lua_table(cls, lua_table: Any) -> Auras[WeakAuraT]:
        raise NotImplementedError

    @classmethod
    def merge(cls, *auras: Auras[WeakAuraT]) -> Iterable[Auras[WeakAuraT]]:
        "Merge auras of the same type."
        return (
            t(__root__=reduce(lambda a, b: {**a, **b}, (i.__root__ for i in a)))
            for t, a in bucketise(auras, key=type).items()
        )


class WeakAura(BaseModel):
    id: str
    uid: str
    parent: O[str]
    url: URL
    version: int

    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True

    _convert_url = validator('url', pre=True)(lambda v: URL(v))


class WeakAuras(Auras[WeakAura]):
    _filename = 'WeakAuras.lua'
    _api_url = URL('https://data.wago.io/api/check/weakauras')

    @classmethod
    def from_lua_table(cls, lua_table: Any) -> WeakAuras:
        auras = (WeakAura.parse_obj(a) for a in lua_table['displays'].values() if a.get('url'))
        return cls(__root__=bucketise(auras, key=lambda a: a.url.parts[1]))


class Plateroo(WeakAura):
    id: str = Field(alias='Name')
    uid = ''


class Plateroos(Auras[Plateroo]):
    _filename = 'Plater.lua'
    _api_url = URL('https://data.wago.io/api/check/plater')

    @classmethod
    def from_lua_table(cls, lua_table: Any) -> Plateroos:
        auras = (
            Plateroo.parse_obj(a)
            for n, p in lua_table['profiles'].items()
            for a in chain(
                ({**p, 'Name': f'__profile_{n}__'},),
                (i for n, v in p.items() if n in {'script_data', 'hook_data'} for i in v),
            )
            if a.get('url')
        )
        return cls(__root__={a.url.parts[1]: [a] for a in auras})


if TYPE_CHECKING:

    class WagoApiChangelog(TypedDict, total=False):
        format: Literal['bbcode', 'markdown']
        text: str

    class WagoApiCommonFields(TypedDict):
        _id: str  # +   # Alphanumeric ID
        name: str  # +  # User-facing name
        slug: str  # +  # Slug if it has one; otherwise same as ``_id``
        url: str
        created: str  # ISO datetime
        modified: str  # ISO datetime
        game: str  # "classic" or xpac, e.g. "bfa"
        username: str  # +  # Author username
        version: int  # +   # Version counter, incremented with every update
        # Semver auto-generated from ``version`` - for presentation only
        versionString: str
        changelog: WagoApiChangelog  # +

    class WagoApiOptionalFields(TypedDict, total=False):
        forkOf: str  # Only present on forks
        regionType: str  # Only present on WAs

    class WagoApiResponse(WagoApiCommonFields, WagoApiOptionalFields):
        pass


class WaCompanionBuilder:
    """A WeakAuras Companion port for shellfolk."""

    def __init__(self, manager: Manager, builder_config: BuilderConfig) -> None:
        self.manager = manager
        self.addon_file = self.manager.config.plugin_dir / __name__ / 'WeakAurasCompanion.zip'
        self.builder_config = builder_config

    @staticmethod
    def extract_auras(model: Type[Auras[Any]], source: str) -> Auras[Any]:
        from ._custom_slpp import slpp

        source_after_assignment = source[source.find('=') + 1 :]
        lua_table = slpp.decode(source_after_assignment)
        return model.from_lua_table(lua_table)

    def extract_installed_auras(self) -> Iterator[Auras[Any]]:
        flavour_root = self.manager.config.addon_dir.parents[1]
        saved_vars_of_every_account = flavour_root.glob('WTF/Account/*/SavedVariables')
        for saved_vars, model in product(
            saved_vars_of_every_account,
            (
                WeakAuras,
                Plateroos,
            ),
        ):
            file = saved_vars / model._filename
            if not file.exists():
                logger.info(f'{file} not found')
            else:
                content = file.read_text(encoding='utf-8-sig', errors='replace')
                aura_group_cache = self.manager.config.cache_dir / shasum(content)
                if aura_group_cache.exists():
                    logger.info(f'loading {file} from cache')
                    aura_groups = model.parse_file(aura_group_cache)
                else:
                    start = time.perf_counter()
                    aura_groups = self.extract_auras(model, content)
                    logger.debug(f'{model.__name__} extracted in {time.perf_counter() - start}s')
                    aura_group_cache.write_text(aura_groups.json(), encoding='utf-8')
                yield aura_groups

    async def get_wago_metadata(self, aura_groups: Auras[Any]) -> List[WagoApiResponse]:
        from aiohttp import ClientResponseError

        from .manager import cache_response

        aura_ids = list(aura_groups.__root__)
        try:
            return await cache_response(
                self.manager,
                aura_groups._api_url.with_query(ids=','.join(aura_ids)),
                30,
                'minutes',
                label='Fetching aura metadata',
                request_kwargs={'headers': {'api-key': self.builder_config.wago_api_key or ''}},
            )
        except ClientResponseError as error:
            if error.status != 404:
                raise
            return []

    async def get_wago_import_string(self, aura_id: str) -> str:
        from .manager import cache_response

        return await cache_response(
            self.manager,
            import_api_url.with_query(id=aura_id),
            30,
            'minutes',
            label=f'Fetching aura with ID {aura_id}',
            to_json=False,
            request_kwargs={'headers': {'api-key': self.builder_config.wago_api_key or ''}},
        )

    async def get_remote_auras(
        self, aura_groups: Auras[WeakAuraT]
    ) -> Tuple[Type[Auras[WeakAuraT]], RemoteAuras]:
        if not aura_groups.__root__:
            return (aura_groups.__class__, [])

        metadata = await self.get_wago_metadata(aura_groups)
        import_strings = await gather(
            (self.get_wago_import_string(r['_id']) for r in metadata), False
        )
        return (
            aura_groups.__class__,
            list(filter(all, zip(aura_groups.__root__.values(), metadata, import_strings))),
        )

    def make_addon(self, auras: Sequence[Tuple[Type[Auras[Any]], RemoteAuras]]) -> None:
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
                # Not using a plain string as the first argument to ``writestr``
                # 'cause the timestamp would be set to the current time
                # which would render the build unreproducible
                zip_info = ZipInfo(filename=f'WeakAurasCompanion/{filename}')
                file.writestr(zip_info, jinja_env.get_template(filename).render(ctx))

            write_tpl(
                'data.lua',
                {
                    'weakauras': [
                        (
                            metadata['slug'],
                            {
                                'name': metadata['name'],
                                'author': metadata['username'],
                                'encoded': import_string,
                                'wagoVersion': metadata['version'],
                                # ``wagoSemver`` is supposed to be the ``versionString``
                                # from Wago but there is a bug where the ``version``
                                # is sometimes not appended to the semver.
                                # The Companion add-on's version is derived from its checksum
                                # so if ``wagoSemver`` were to change between requests
                                # we'd be triggering spurious updates in instawow.
                                'wagoSemver': metadata['version'],
                                'versionNote': metadata['changelog'].get('text', ''),
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
                            metadata['slug'],
                            {
                                'name': metadata['name'],
                                'author': metadata['username'],
                                'encoded': import_string,
                                'wagoVersion': metadata['version'],
                                'wagoSemver': metadata['version'],
                                'versionNote': metadata['changelog'].get('text', ''),
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
                {'interface': '11305' if self.manager.config.is_classic else '90001'},
            )

    async def build(self) -> None:
        installed_auras = await t(list)(self.extract_installed_auras())
        installed_auras_by_type = Auras.merge(*installed_auras)
        remote_auras = await gather(map(self.get_remote_auras, installed_auras_by_type), False)
        await t(self.make_addon)(remote_auras)

    def checksum(self) -> str:
        from hashlib import sha256

        return sha256(self.addon_file.read_bytes()).hexdigest()
