from __future__ import annotations

import importlib.resources
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import timedelta
from functools import reduce
from itertools import chain, product
from typing import Literal, TypeAlias, cast

import cattrs
from typing_extensions import NotRequired as N
from typing_extensions import TypedDict
from yarl import URL

from instawow import http, shared_ctx
from instawow._logging import logger
from instawow._progress_reporting import make_default_progress, make_incrementing_progress_tracker
from instawow._utils.aio import gather, run_in_thread
from instawow._utils.compat import StrEnum, fauxfrozen
from instawow._utils.iteration import bucketise
from instawow._utils.perf import time_op
from instawow._utils.text import shasum
from instawow.config import ProfileConfig
from instawow.wow_installations import get_installation_dir_from_addon_dir

from ._config import PluginConfig

_LuaTable: TypeAlias = Mapping[str, '_LuaTable']
_Auras: TypeAlias = 'WeakAuras | Plateroos'
_Match: TypeAlias = tuple[Sequence['WeakAura | Plateroo'], '_WagoApiResponse', str]


class _WagoApiResponse(TypedDict):
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
    changelog: _WagoApiResponse_Changelog  # +
    forkOf: N[str]  # Only present on forks
    regionType: N[str]  # Only present on WAs


class _WagoApiResponse_Changelog(TypedDict):
    format: N[Literal['bbcode', 'markdown']]
    text: N[str]


_CHECK_API_URL = URL('https://data.wago.io/api/check')
_IMPORT_STRING_API_URL = URL('https://data.wago.io/api/raw/encoded')

_aura_converter = cattrs.Converter()
_aura_converter.register_structure_hook(URL, lambda v, _: URL(v))
_aura_converter.register_unstructure_hook(URL, str)


@fauxfrozen(kw_only=True)
class WeakAura:
    id: str
    uid: str
    parent: str | None = None
    url: URL
    version: int

    @classmethod
    def from_lua_table(cls, lua_table: _LuaTable):
        url_string = lua_table.get('url')
        if url_string is not None:
            weakaura = _aura_converter.structure(lua_table, cls)
            if weakaura.url.host == 'wago.io':
                return weakaura


@fauxfrozen(kw_only=True)
class Plateroo(WeakAura):
    uid: str = ''

    @classmethod
    def from_lua_table(cls, lua_table: _LuaTable):
        return super().from_lua_table({**lua_table, 'id': lua_table['Name']})


@fauxfrozen
class WeakAuras:
    api_ep = 'weakauras'
    addon_name = 'WeakAuras'

    root: dict[str, list[WeakAura]]

    @classmethod
    def from_lua_table(cls, lua_table: _LuaTable):
        raw_auras = lua_table['WeakAurasSaved']['displays']
        auras = (WeakAura.from_lua_table(t) for t in raw_auras.values())
        sorted_auras = sorted(filter(None, auras), key=lambda a: a.id)
        return cls(bucketise(sorted_auras, key=lambda a: a.url.parts[1]))


@fauxfrozen
class Plateroos:
    api_ep = 'plater'
    addon_name = 'Plater'

    root: dict[str, list[Plateroo]]

    @classmethod
    def from_lua_table(cls, lua_table: _LuaTable):
        raw_auras = lua_table['PlaterDB']['profiles']
        auras = (
            Plateroo.from_lua_table(cast(_LuaTable, t))
            for n, p in raw_auras.items()
            for t in chain(
                ({**p, 'Name': f'__profile_{n}__'},),
                p.get('script_data') or (),
                p.get('hook_data') or (),
            )
        )
        sorted_auras = sorted(filter(None, auras), key=lambda a: a.id)
        return cls({a.url.parts[1]: [a] for a in sorted_auras})


def _merge_auras(auras: Iterable[_Auras]):
    return {
        t: t(reduce(lambda a, b: a | b, (i.root for i in a)))
        for t, a in bucketise(auras, key=type).items()
    }


class _TocNumber(StrEnum):
    Retail = '100206'
    VanillaClassic = '11502'
    Classic = '40400'
    WrathClassic = '30403'


class WaCompanionBuilder:
    """A WeakAuras Companion port for shellfolk."""

    def __init__(self, profile_config: ProfileConfig) -> None:
        self._profile_config = profile_config
        self.config = PluginConfig(self._profile_config, __spec__.parent)

    def _make_request_headers(self):
        access_token = self.config.access_token
        if access_token:
            return {'api-key': access_token}

    @staticmethod
    def extract_auras(model: type[_Auras], source: str) -> _Auras:
        from ._custom_slpp import loads

        return model.from_lua_table(loads(f'{{{source}}}'))

    def extract_installed_auras(self) -> Iterator[_Auras]:
        installation_dir = get_installation_dir_from_addon_dir(self._profile_config.addon_dir)
        if not installation_dir:
            raise ValueError(
                f'cannot extract installation folder from {self._profile_config.addon_dir}'
            )

        saved_vars_by_account = installation_dir.glob('WTF/Account/*/SavedVariables')
        for saved_vars, model in product(
            saved_vars_by_account,
            [WeakAuras, Plateroos],
        ):
            file = (saved_vars / model.addon_name).with_suffix('.lua')
            if not file.exists():
                logger.info(f'{file} not found')
            else:
                content = file.read_text(encoding='utf-8-sig', errors='replace')
                aura_group_cache = self.config.cache_dir / shasum(content)
                if aura_group_cache.exists():
                    logger.info(f'loading {file} from cache at {aura_group_cache}')
                    aura_group_json = json.loads(aura_group_cache.read_bytes())
                    aura_group = _aura_converter.structure({'root': aura_group_json}, model)
                else:
                    with time_op(
                        lambda t: logger.debug(
                            f'extracted {model.__name__} in {t:.3f}s'  # noqa: B023
                        )
                    ):
                        aura_group = self.extract_auras(model, content)
                    aura_group_cache.write_text(
                        json.dumps(_aura_converter.unstructure(aura_group.root)),
                        encoding='utf-8',
                    )
                yield aura_group

    async def _fetch_wago_metadata(self, api_ep: str, aura_ids: Iterable[str]):
        async with shared_ctx.web_client.post(
            (_CHECK_API_URL / api_ep),
            expire_after=timedelta(minutes=30),
            headers=self._make_request_headers(),
            json={'ids': list(aura_ids)},
            trace_request_ctx={
                'progress': make_default_progress(type_='download', label='Fetching aura metadata')
            },
        ) as response:
            metadata: list[_WagoApiResponse]
            if response.status == 404:
                metadata = []
                return metadata

            response.raise_for_status()

            metadata = await response.json()
            return sorted(metadata, key=lambda r: r['slug'])

    async def _fetch_wago_import_string(self, remote_aura: _WagoApiResponse):
        async with shared_ctx.web_client.get(
            _IMPORT_STRING_API_URL.with_query(id=remote_aura['_id']).with_fragment(
                str(remote_aura['version'])
            ),
            expire_after=http.CACHE_INDEFINITELY,
            headers=self._make_request_headers(),
            raise_for_status=True,
        ) as response:
            return await response.text()

    async def get_remote_auras(self, aura_group: _Auras) -> list[_Match]:
        if not aura_group.root:
            return []

        metadata = await self._fetch_wago_metadata(aura_group.api_ep, aura_group.root)

        track_progress = make_incrementing_progress_tracker(
            len(metadata), f'Fetching import strings: {aura_group.addon_name}'
        )

        import_strings = await gather(
            track_progress(self._fetch_wago_import_string(r)) for r in metadata
        )
        return [
            (aura_group.root.get(r['slug']) or aura_group.root[r['_id']], r, i)
            for r, i in zip(metadata, import_strings)
        ]

    def _generate_addon(self, auras: Iterable[tuple[type[_Auras], list[_Match]]]):
        from zipfile import ZipFile, ZipInfo

        from . import _templates

        template_resources = importlib.resources.files(_templates)

        aura_dict = dict.fromkeys((WeakAuras, Plateroos), list[_Match]()) | dict(auras)

        with ZipFile(self.config.addon_zip_file, 'w') as file:

            def write_file(filename: str, content: str):
                # Not using a plain string as the first argument to ``writestr``
                # 'cause the timestamp would be set to the current time
                # which would render the build unreproducible.
                file.writestr(
                    ZipInfo(filename=f'WeakAurasCompanion/{filename}'),
                    content,
                )
                return content

            def make_slug_entry(metadata: _WagoApiResponse, import_string: str):
                return f"""\
            [ [=[{metadata['slug']}]=] ] = {{
                name = [=[{metadata['name']}]=],
                author = [=[{metadata.get('username', '__unknown__')}]=],
                encoded = [=[{import_string}]=],
                wagoVersion = [=[{metadata['version']}]=],
                wagoSemver = [=[{metadata['version']}]=],
                versionNote = [=[{metadata['changelog'].get('text', '')}]=],
                source = [=[Wago]=],
            }},"""

            NL = '\n'
            data_output = write_file(
                'data.lua',
                f'''\
-- file generated automatically
WeakAurasCompanionData = {{
{NL.join(f"""
    {c.addon_name} = {{
        slugs = {{
{NL.join(make_slug_entry(m, i) for _, m, i in v)}
        }},
        stash = {{
        }},
        stopmotionFiles = {{
        }},
    }},"""
    for c, v in aura_dict.items()
)}
}}
''',
            )

            init_output = write_file(
                'init.lua', template_resources.joinpath('init.lua').read_text()
            )

            interface_version = self._profile_config.game_flavour.to_flavour_keyed_enum(_TocNumber)
            addon_version = shasum(data_output, init_output, interface_version)[:7]

            toc_tpl = template_resources.joinpath('WeakAurasCompanion.toc').read_text()
            write_file(
                'WeakAurasCompanion.toc',
                toc_tpl.format(
                    interface=self._profile_config.game_flavour.to_flavour_keyed_enum(_TocNumber),
                    version=addon_version,
                ),
            )

        changelog_tpl = template_resources.joinpath('CHANGELOG.md').read_text()
        self.config.changelog_file.write_text(
            '\n\n'.join(
                changelog_tpl.format(
                    name=a.id,
                    url=a.url.parent,
                    version=metadata['version'],
                    changelog=metadata['changelog'].get('text') or 'n/a',
                )
                for v in aura_dict.values()
                for existing_auras, metadata, _ in v
                for a in (next((i for i in existing_auras if not i.parent), existing_auras[0]),)
                if a.version != metadata['version']
            )
            or 'n/a',
            encoding='utf-8',
        )

        self.config.version_file.write_text(
            addon_version,
            encoding='utf-8',
        )

    async def build(self) -> None:
        await run_in_thread(self.config.ensure_dirs)()

        installed_auras_by_type = _merge_auras(
            await run_in_thread(list[_Auras])(self.extract_installed_auras()),
        )
        remote_auras = await gather(
            self.get_remote_auras(r) for r in installed_auras_by_type.values()
        )
        await run_in_thread(self._generate_addon)(zip(installed_auras_by_type, remote_auras))

    def get_version(self) -> str:
        return self.config.version_file.read_text(encoding='utf-8')
