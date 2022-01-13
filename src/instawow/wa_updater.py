from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from functools import partial, reduce
from itertools import chain, product
import time
import typing
from typing import Any, ClassVar, TypeVar

from loguru import logger
from pydantic import BaseModel, Field, validator
from typing_extensions import Literal
from typing_extensions import NotRequired as N
from typing_extensions import Self, TypeAlias, TypedDict
from yarl import URL

from .common import Flavour
from .manager import Manager
from .utils import StrEnum, bucketise, chain_dict, gather
from .utils import run_in_thread as t
from .utils import shasum

_TAuras = TypeVar('_TAuras', bound='BaseAuras')
_ImportString = _Slug = str
_AuraGroup: TypeAlias = 'Sequence[tuple[Sequence[WeakAura], WagoApiResponse, _ImportString]]'

IMPORT_API_URL = URL('https://data.wago.io/api/raw/encoded')


class BaseAuras(
    BaseModel,
    arbitrary_types_allowed=True,
    json_encoders={URL: str},
):
    api_url: ClassVar[URL]
    filename: ClassVar[str]

    __root__: typing.Dict[_Slug, typing.List[Any]]

    @classmethod
    def from_lua_table(cls, lua_table: Any) -> Self:
        raise NotImplementedError


def _merge_auras(auras: Iterable[_TAuras]) -> dict[type[_TAuras], _TAuras]:
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

    @classmethod
    def from_lua_table(cls, lua_table: Any):
        url_string = lua_table.get('url')
        if url_string is not None:
            url = URL(url_string)
            if url.host == 'wago.io':
                return cls.parse_obj({**lua_table, 'url': url})

    @validator('url', pre=True)
    def _url_to_URL(cls, value: str | URL):
        if not isinstance(value, URL):
            value = URL(value)
        return value


class WeakAuras(BaseAuras):
    api_url = URL('https://data.wago.io/api/check/weakauras')
    filename = 'WeakAuras.lua'

    __root__: typing.Dict[_Slug, typing.List[WeakAura]]

    @classmethod
    def from_lua_table(cls, lua_table: Any):
        auras = (
            a for t in lua_table['displays'].values() for a in (WeakAura.from_lua_table(t),) if a
        )
        sorted_auras = sorted(auras, key=lambda a: a.id)
        return cls(__root__=bucketise(sorted_auras, key=lambda a: a.url.parts[1]))


class Plateroo(WeakAura):
    id: str = Field(alias='Name')
    uid = ''


class Plateroos(BaseAuras):
    api_url = URL('https://data.wago.io/api/check/plater')
    filename = 'Plater.lua'

    __root__: typing.Dict[_Slug, typing.List[Plateroo]]

    @classmethod
    def from_lua_table(cls, lua_table: Any):
        auras = (
            a
            for n, p in lua_table['profiles'].items()
            for t in chain(
                ({**p, 'Name': f'__profile_{n}__'},),
                p.get('script_data') or (),
                p.get('hook_data') or (),
            )
            for a in (Plateroo.from_lua_table(t),)
            if a
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
    username: N[str]  # +  # Author username
    version: int  # +   # Version counter, incremented with every update
    # Semver auto-generated from ``version`` - for presentation only
    versionString: str
    changelog: WagoApiResponse_Changelog  # +
    forkOf: N[str]  # Only present on forks
    regionType: N[str]  # Only present on WAs


class WagoApiResponse_Changelog(TypedDict):
    format: N[Literal['bbcode', 'markdown']]
    text: N[str]


class _TocNumbers(StrEnum):
    retail = '90105'
    vanilla_classic = '11400'
    burning_crusade_classic = '20502'


class WaCompanionBuilder:
    """A WeakAuras Companion port for shellfolk."""

    def __init__(self, manager: Manager) -> None:
        self.manager = manager

        self.access_token = self.manager.config.global_config.access_tokens.wago

        output_folder = self.manager.config.plugin_dir / __name__
        self.addon_zip_path = output_folder / 'WeakAurasCompanion.zip'
        self.changelog_path = output_folder / 'CHANGELOG.md'
        self.checksum_txt_path = output_folder / 'checksum.txt'

    @staticmethod
    def extract_auras(model: type[_TAuras], source: str) -> _TAuras:
        from ._custom_slpp import loads

        lua_table = loads(f'{{{source}}}')
        (aura_table,) = lua_table.values()
        return model.from_lua_table(aura_table)

    def extract_installed_auras(self) -> Iterator[WeakAuras | Plateroos]:
        flavour_root = self.manager.config.addon_dir.parents[1]
        saved_vars_by_account = flavour_root.glob('WTF/Account/*/SavedVariables')
        for saved_vars, model in product(
            saved_vars_by_account,
            [WeakAuras, Plateroos],
        ):
            file = saved_vars / model.filename
            if not file.exists():
                logger.info(f'{file} not found')
            else:
                content = file.read_text(encoding='utf-8-sig', errors='replace')
                aura_group_cache = self.manager.config.global_config.cache_dir / shasum(content)
                if aura_group_cache.exists():
                    logger.info(f'loading {file} from cache at {aura_group_cache}')
                    aura_groups = model.parse_file(aura_group_cache)
                else:
                    start = time.perf_counter()
                    aura_groups = self.extract_auras(model, content)
                    logger.debug(
                        f'extracted {model.__name__} in {time.perf_counter() - start:.3f}s'
                    )
                    aura_group_cache.write_text(aura_groups.json(), encoding='utf-8')
                yield aura_groups

    async def _fetch_wago_metadata(self, api_url: URL, aura_ids: Iterable[str]):
        async with self.manager.web_client.get(
            api_url.with_query(ids=','.join(aura_ids)),
            {'minutes': 30},
            label='Fetching aura metadata',
            headers={
                'api-key': self.access_token.get_secret_value()
                if self.access_token is not None
                else ''
            },
        ) as response:
            metadata: list[WagoApiResponse]
            if response.status == 404:
                metadata = []
                return metadata
            response.raise_for_status()
            metadata = await response.json()
            return sorted(metadata, key=lambda r: r['slug'])

    async def _fetch_wago_import_string(self, aura: WagoApiResponse):
        async with self.manager.web_client.get(
            IMPORT_API_URL.with_query(id=aura['_id']).with_fragment(str(aura['version'])),
            {'days': 30},
            headers={
                'api-key': self.access_token.get_secret_value()
                if self.access_token is not None
                else ''
            },
            label=f"Fetching aura '{aura['slug']}'",
            raise_for_status=True,
        ) as response:
            return await response.text()

    async def get_remote_auras(self, auras: BaseAuras) -> _AuraGroup:
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

    def _generate_addon(
        self, auras: Iterable[tuple[type[WeakAuras | Plateroos], _AuraGroup]]
    ) -> None:
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
                {
                    'interface': Flavour.to_flavour_keyed_enum(
                        _TocNumbers, self.manager.config.game_flavour
                    )
                },
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
