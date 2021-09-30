from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from functools import partial, reduce
from itertools import chain, product
import time
import typing
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from loguru import logger
from pydantic import BaseModel, Field, validator
from pydantic.generics import GenericModel
from typing_extensions import Literal, TypeAlias, TypedDict
from yarl import URL

from . import manager
from .config import BaseConfig, Flavour
from .utils import bucketise, chain_dict, gather
from .utils import run_in_thread as t
from .utils import shasum

# ``NotRequired`` is provisional and does not exist at runtime
if TYPE_CHECKING:  # pragma: no cover
    from typing_extensions import NotRequired as Ν


_ImportString: TypeAlias = str
_Slug: TypeAlias = str
AuraGroup: TypeAlias = 'Sequence[tuple[Sequence[WeakAura], WagoApiResponse, _ImportString]]'

_TWeakAura = TypeVar('_TWeakAura', bound='WeakAura', covariant=True)

IMPORT_API_URL = URL('https://data.wago.io/api/raw/encoded')


class BuilderConfig(BaseConfig):
    wago_api_key: typing.Optional[str] = None


class Auras(
    GenericModel,
    Generic[_TWeakAura],
    arbitrary_types_allowed=True,
    json_encoders={URL: str},
):
    api_url: ClassVar[URL]
    filename: ClassVar[str]

    __root__: typing.Dict[_Slug, typing.List[_TWeakAura]]

    @classmethod
    def from_lua_table(cls, lua_table: Any) -> Auras[_TWeakAura]:
        raise NotImplementedError


def _merge_auras(auras: Iterable[Auras[WeakAura]]) -> dict[type, Auras[WeakAura]]:
    "Merge auras of the same type."
    return {
        t: t(__root__=reduce(lambda a, b: {**a, **b}, (i.__root__ for i in a)))
        for t, a in bucketise(auras, key=type).items()
    }


class WeakAura(
    BaseModel,
    allow_population_by_field_name=True,
    arbitrary_types_allowed=True,
):
    id: str
    uid: str
    parent: typing.Optional[str]
    url: URL
    version: int

    @validator('url', pre=True)
    def _convert_url(cls, value: str) -> URL:
        return URL(value)


class WeakAuras(Auras[WeakAura]):
    api_url = URL('https://data.wago.io/api/check/weakauras')
    filename = 'WeakAuras.lua'

    @classmethod
    def from_lua_table(cls, lua_table: Any) -> WeakAuras:
        auras = (WeakAura.parse_obj(a) for a in lua_table['displays'].values() if a.get('url'))
        sorted_auras = sorted(auras, key=lambda a: a.id)
        return cls(__root__=bucketise(sorted_auras, key=lambda a: a.url.parts[1]))


class Plateroo(WeakAura):
    id: str = Field(alias='Name')
    uid = ''


class Plateroos(Auras[Plateroo]):
    api_url = URL('https://data.wago.io/api/check/plater')
    filename = 'Plater.lua'

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
        sorted_auras = sorted(auras, key=lambda a: a.id)
        return cls(__root__={a.url.parts[1]: [a] for a in sorted_auras})


class WagoApiResponse(TypedDict):
    _id: str  # +   # Alphanumeric ID
    name: str  # +  # User-facing name
    slug: str  # +  # Slug if it has one; otherwise same as ``_id``
    url: str
    created: str  # ISO datetime
    modified: str  # ISO datetime
    game: str  # "classic" or xpac, e.g. "bfa"
    username: Ν[str]  # +  # Author username
    version: int  # +   # Version counter, incremented with every update
    # Semver auto-generated from ``version`` - for presentation only
    versionString: str
    changelog: WagoApiResponse_Changelog  # +
    forkOf: Ν[str]  # Only present on forks
    regionType: Ν[str]  # Only present on WAs


class WagoApiResponse_Changelog(TypedDict):
    format: Ν[Literal['bbcode', 'markdown']]
    text: Ν[str]


class WaCompanionBuilder:
    """A WeakAuras Companion port for shellfolk."""

    def __init__(self, manager: manager.Manager, builder_config: BuilderConfig) -> None:
        self.manager = manager
        self.builder_config = builder_config

        output_folder = self.manager.config.plugin_dir / __name__
        self.addon_zip_path = output_folder / 'WeakAurasCompanion.zip'
        self.changelog_path = output_folder / 'CHANGELOG.md'
        self.checksum_txt_path = output_folder / 'checksum.txt'

    @staticmethod
    def extract_auras(model: type[Auras[WeakAura]], source: str) -> Auras[WeakAura]:
        from ._custom_slpp import SLPP

        source_after_assignment = source[source.find('=') + 1 :]
        lua_table = SLPP(source_after_assignment).decode()
        return model.from_lua_table(lua_table)

    def extract_installed_auras(self) -> Iterator[Auras[WeakAura]]:
        flavour_root = self.manager.config.addon_dir.parents[1]
        saved_vars_of_every_account = flavour_root.glob('WTF/Account/*/SavedVariables')
        for saved_vars, model in product(
            saved_vars_of_every_account,
            [WeakAuras, Plateroos],
        ):
            file = saved_vars / model.filename
            if not file.exists():
                logger.info(f'{file} not found')
            else:
                content = file.read_text(encoding='utf-8-sig', errors='replace')
                aura_group_cache = self.manager.config.cache_dir / shasum(content)
                if aura_group_cache.exists():
                    logger.info(f'loading {file} from cache at {aura_group_cache}')
                    aura_groups = model.parse_file(aura_group_cache)
                else:
                    start = time.perf_counter()
                    aura_groups = self.extract_auras(model, content)
                    logger.debug(f'{model.__name__} extracted in {time.perf_counter() - start}s')
                    aura_group_cache.write_text(aura_groups.json(), encoding='utf-8')
                yield aura_groups

    async def _fetch_wago_metadata(
        self, api_url: URL, aura_ids: Iterable[str]
    ) -> list[WagoApiResponse]:
        from aiohttp import ClientResponseError

        try:
            return sorted(
                await manager.cache_response(
                    self.manager,
                    api_url.with_query(ids=','.join(aura_ids)),
                    {'minutes': 30},
                    label='Fetching aura metadata',
                    request_extra={'headers': {'api-key': self.builder_config.wago_api_key or ''}},
                ),
                key=lambda r: r['slug'],
            )
        except ClientResponseError as error:
            if error.status != 404:
                raise
            return []

    async def _fetch_wago_import_string(self, aura: WagoApiResponse) -> str:
        return await manager.cache_response(
            self.manager,
            IMPORT_API_URL.with_query(id=aura['_id']).with_fragment(str(aura['version'])),
            {'days': 30},
            label=f"Fetching aura '{aura['slug']}'",
            is_json=False,
            request_extra={'headers': {'api-key': self.builder_config.wago_api_key or ''}},
        )

    async def get_remote_auras(self, auras: Auras[WeakAura]) -> AuraGroup:
        if not auras.__root__:
            return []

        metadata = await self._fetch_wago_metadata(auras.api_url, auras.__root__)
        import_strings = await gather(self._fetch_wago_import_string(r) for r in metadata)
        return [(auras.__root__[r['slug']], r, i) for r, i in zip(metadata, import_strings)]

    def _checksum(self) -> str:
        from hashlib import sha256

        return sha256(self.addon_zip_path.read_bytes()).hexdigest()

    async def get_checksum(self) -> str:
        return await t(self.checksum_txt_path.read_text)(encoding='utf-8')

    def _get_toc_number(self) -> str:
        game_flavour: Flavour = self.manager.config.game_flavour
        if game_flavour is Flavour.retail:
            return '90100'
        elif game_flavour is Flavour.vanilla_classic:
            return '11400'
        elif game_flavour is Flavour.burning_crusade_classic:
            return '20502'

    def _generate_addon(self, auras: Iterable[tuple[type[Auras[WeakAura]], AuraGroup]]) -> None:
        from importlib.resources import read_text
        from zipfile import ZipFile, ZipInfo

        from jinja2 import Environment, FunctionLoader

        from . import wa_templates

        jinja_env = Environment(
            trim_blocks=True,
            lstrip_blocks=True,
            loader=FunctionLoader(partial(read_text, wa_templates)),
        )
        aura_dict = chain_dict((WeakAuras, Plateroos), (), auras)

        self.addon_zip_path.parent.mkdir(exist_ok=True)
        with ZipFile(self.addon_zip_path, 'w') as file:

            def write_tpl(filename: str, ctx: dict[str, Any]):
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
                                'author': metadata.get('username', '__unknown__'),
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
                                'author': metadata.get('username', '__unknown__'),
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
                {'interface': self._get_toc_number()},
            )

        self.changelog_path.write_text(
            jinja_env.get_template(self.changelog_path.name).render(
                {
                    'changelog_entries': [
                        (
                            a.id,
                            a.url.parent,
                            metadata['version'],
                            metadata['changelog'].get('text') or 'n/a',
                        )
                        for v in aura_dict.values()
                        for existing_auras, metadata, _ in v
                        for a in (
                            next((i for i in existing_auras if not i.parent), existing_auras[0]),
                        )
                        if a.version != metadata['version']
                    ]
                }
            )
            or 'n/a',
            encoding='utf-8',
        )

        self.checksum_txt_path.write_text(
            self._checksum(),
            encoding='utf-8',
        )

    async def build(self) -> None:
        installed_auras = await t(list)(self.extract_installed_auras())
        installed_auras_by_type = _merge_auras(installed_auras)
        aura_groups = await gather(map(self.get_remote_auras, installed_auras_by_type.values()))
        await t(self._generate_addon)(zip(installed_auras_by_type, aura_groups))
