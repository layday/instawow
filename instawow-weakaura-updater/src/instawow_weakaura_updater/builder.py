from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Mapping, Sequence
from itertools import chain, product
from operator import itemgetter
from pathlib import Path
from typing import Any, Literal, NotRequired, Protocol, TypedDict

import cattrs
from yarl import URL

from instawow import http, http_ctx
from instawow._logging import logger
from instawow._utils.aio import gather, run_in_thread
from instawow._utils.attrs import fauxfrozen
from instawow._utils.iteration import bucketise, uniq
from instawow._utils.perf import time_op
from instawow.progress_reporting import make_download_progress, make_incrementing_progress_tracker
from instawow.wow_installations import (
    extract_installation_dir_from_addon_dir,
    extract_installation_version_from_addon_dir,
)

from ._utils import get_checksum
from .config import PluginConfig

_saved_vars_cache_name = '_saved_vars_v1'

_api_base_url = URL('https://data.wago.io/api')

_aura_converter = cattrs.Converter()
_aura_converter.register_structure_hook(URL, lambda v, _: URL(v))
_aura_converter.register_unstructure_hook(URL, str)


class _WagoApiResponse(TypedDict):
    _id: str
    'Alphanumeric ID'
    name: str
    'User-facing name'
    slug: str
    'Slug if it has one; otherwise same as ``_id``'
    url: str
    created: str
    'ISO datetime'
    modified: str
    'ISO datetime'
    game: str
    'Xpac name, e.g. "bfa"'
    username: NotRequired[str]
    'Author username'
    version: int
    'Version counter, incremented with every update'
    versionString: str
    'Semver auto-generated from ``version`` - for presentation only'
    changelog: _WagoApiResponse_Changelog
    forkOf: NotRequired[str]
    'Only present on forks'
    regionType: NotRequired[str]
    'Only present on WAs'


class _WagoApiResponse_Changelog(TypedDict):
    format: NotRequired[Literal['bbcode', 'markdown']]
    text: NotRequired[str]


@fauxfrozen(kw_only=True)
class _Aura:
    id: str
    uid: str
    parent: str | None = None
    url: URL
    version: int


type _AuraGroup = dict[str, list[_Aura]]


class _AuraAddon(Protocol):  # pragma: no cover
    name: str
    api_endpoint: str

    def extract_auras(self, lua_table: Any) -> _AuraGroup: ...


@object.__new__
class _WeakAuras(_AuraAddon):
    name = 'WeakAuras'
    api_endpoint = 'weakauras'

    def extract_auras(self, lua_table: Any):
        raw_auras = lua_table['WeakAurasSaved']['displays']
        prepared_auras = (t for t in raw_auras.values() if t.get('url'))
        auras = _aura_converter.structure(prepared_auras, list[_Aura])
        sorted_auras = sorted(
            filter(lambda a: not a.parent and a.url.host == 'wago.io', auras), key=lambda a: a.id
        )
        return bucketise(sorted_auras, key=lambda a: a.url.parts[1])


@object.__new__
class _Plateroos(_AuraAddon):
    name = 'Plater'
    api_endpoint = 'plater'

    def extract_auras(self, lua_table: Any):
        raw_auras = lua_table['PlaterDB']['profiles']
        prepared_auras = (
            {**t, 'id': t['Name'], 'uid': ''}
            for n, p in raw_auras.items()
            for t in chain(
                ({**p, 'Name': f'__profile_{n}__'},),
                p.get('script_data') or (),
                p.get('hook_data') or (),
            )
            if t.get('url')
        )
        auras = _aura_converter.structure(prepared_auras, list[_Aura])
        sorted_auras = sorted(
            filter(lambda a: not a.parent and a.url.host == 'wago.io', auras), key=lambda a: a.id
        )
        return {a.url.parts[1]: [a] for a in sorted_auras}


@fauxfrozen
class _BuildPaths:
    archive: Path
    changelog: Path
    version: Path


async def _get_remote_auras(
    plugin_config: PluginConfig, aura_addon: _AuraAddon, aura_ids: list[str]
):
    if not aura_ids:
        return ()

    access_token = plugin_config.access_tokens.wago
    request_headers = {'api-key': access_token} if access_token else None

    async with http_ctx.web_client().post(
        _api_base_url / 'check' / aura_addon.api_endpoint,
        expire_after=dt.timedelta(minutes=30),
        headers=request_headers,
        json={'ids': aura_ids},
        trace_request_ctx={'progress': make_download_progress(label='Fetching aura metadata')},
    ) as response:
        if response.status == 404:
            return ()

        response.raise_for_status()

        metadata: list[_WagoApiResponse] = sorted(
            await response.json(),
            key=itemgetter('slug'),
        )

    async def fetch_wago_import_string(remote_aura: _WagoApiResponse):
        async with http_ctx.web_client().get(
            (_api_base_url / 'raw' / 'encoded')
            .with_query(id=remote_aura['_id'])
            .with_fragment(str(remote_aura['version'])),
            expire_after=http.CACHE_INDEFINITELY,
            headers=request_headers,
            raise_for_status=True,
        ) as response:
            return await response.text()

    track_import_string_progress = make_incrementing_progress_tracker(
        len(metadata), f'Fetching import strings for {aura_addon.name}'
    )
    import_strings = await gather(
        track_import_string_progress(fetch_wago_import_string(r)) for r in metadata
    )

    return list(zip(metadata, import_strings))


def _generate_addon(
    plugin_config: PluginConfig,
    aura_groups: Mapping[_AuraAddon, Sequence[tuple[_WagoApiResponse, str]]],
):
    from zipfile import ZipFile, ZipInfo

    build_paths = get_build_paths(
        plugin_config.ensure_dirs(),
    )

    with ZipFile(build_paths.archive, 'w') as file:

        def write_file(filename: str, content: str):
            # Not using a plain string as the first argument to ``writestr``
            # 'cause the timestamp would be set to the current time
            # which would render the build unreproducible.
            file.writestr(ZipInfo(filename=f'WeakAurasCompanion/{filename}'), content)
            return content

        data_output = write_file(
            'data.lua',
            f"""\
-- file generated automatically
WeakAurasCompanionData = {{
{
                '\n'.join(
                    f'''\
    {addon.name} = {{
        slugs = {{
{
                        '\n'.join(
                            f"""\
            [ [=[{metadata['slug']}]=] ] = {{
                name = [=[{metadata['name']}]=],
                author = [=[{metadata.get('username', '__unknown__')}]=],
                encoded = [=[{import_string}]=],
                wagoVersion = [=[{metadata['version']}]=],
                wagoSemver = [=[{metadata['version']}]=],
                versionNote = [=[{metadata['changelog'].get('text', '')}]=],
                source = [=[Wago]=],
            }},"""
                            for metadata, import_string in g
                        )
                    }
        }},
        stash = {{
        }},
        stopmotionFiles = {{
        }},
    }},'''
                    for addon, g in aura_groups.items()
                )
            }
}}
""",
        )

        init_output = write_file(
            'init.lua',
            """\
-- file generated automatically
local loadedFrame = CreateFrame("FRAME")
loadedFrame:RegisterEvent("ADDON_LOADED")
loadedFrame:SetScript("OnEvent", function(_, _, addonName)
  if addonName == "WeakAurasCompanion" then
    if WeakAuras and WeakAuras.AddCompanionData and WeakAurasCompanionData then
      local WeakAurasData = WeakAurasCompanionData.WeakAuras
      if WeakAurasData then
        WeakAuras.AddCompanionData(WeakAurasData)
        WeakAuras.StopMotion.texture_types["WeakAuras Companion"] = WeakAuras.StopMotion.texture_types["WeakAuras Companion"] or {}
        local CompanionTextures = WeakAuras.StopMotion.texture_types["WeakAuras Companion"]
        for fileName, name in pairs(WeakAurasData.stopmotionFiles) do
          CompanionTextures["Interface\\\\AddOns\\\\WeakAurasCompanion\\\\animations\\\\" .. fileName] = name
        end
      end
    end

    if Plater and Plater.AddCompanionData and WeakAurasCompanionData and WeakAurasCompanionData.Plater then
      Plater.AddCompanionData(WeakAurasCompanionData.Plater)
    end
  end
end)
""",
        )

        interface_version = (
            extract_installation_version_from_addon_dir(plugin_config.profile_config.addon_dir)
            or 0
        )
        addon_version = get_checksum(data_output, init_output, interface_version)[:7]

        write_file(
            'WeakAurasCompanion.toc',
            f"""\
## Interface: {interface_version}
## Title: WeakAuras Companion
## Author: The WeakAuras Team
## X-Generator: instawow
## Version: {addon_version}
## IconTexture: Interface\\AddOns\\WeakAuras\\Media\\Textures\\icon.blp
## Notes: Keep your WeakAuras updated!
## DefaultState: Enabled
## LoadOnDemand: 0
## Dependencies: WeakAuras
## OptionalDeps: {','.join(a.name for a in aura_groups if a.name != 'WeakAuras')}

data.lua
init.lua
""",
        )

    build_paths.changelog.write_text(
        '\n\n'.join(
            f"""\
## {m['name']} v{m['version']} ({m['url']})

{m['changelog'].get('text') or 'n/a'}
"""
            for g in aura_groups.values()
            for m, _ in g
        )
        or 'n/a',
        encoding='utf-8',
    )

    build_paths.version.write_text(
        addon_version,
        encoding='utf-8',
    )

    return build_paths


async def build_addon(plugin_config: PluginConfig) -> _BuildPaths:
    installed_auras = await run_in_thread(list)(extract_installed_auras(plugin_config))
    grouped_aura_ids = {
        a: uniq(k for *_, g in v for k in g)
        for a, v in bucketise(installed_auras, key=itemgetter(1)).items()
    }
    remote_auras = await gather(
        _get_remote_auras(plugin_config, *v) for v in grouped_aura_ids.items()
    )
    return await run_in_thread(_generate_addon)(
        plugin_config, dict(zip(grouped_aura_ids, remote_auras))
    )


def extract_installed_auras(
    plugin_config: PluginConfig,
) -> Iterator[tuple[str, _AuraAddon, _AuraGroup]]:
    import diskcache

    installation_dir = extract_installation_dir_from_addon_dir(
        plugin_config.profile_config.addon_dir
    )
    if not installation_dir:
        raise ValueError(
            f'Cannot determine installation folder from {plugin_config.profile_config.addon_dir}'
        )

    with diskcache.Cache(
        plugin_config.dirs.cache / _saved_vars_cache_name,
    ) as cache:
        for account_sv_path, addon in product(
            installation_dir.glob('WTF/Account/*/SavedVariables'), (_WeakAuras, _Plateroos)
        ):
            sv_path = (account_sv_path / addon.name).with_suffix('.lua')
            if not sv_path.exists():
                continue

            content = sv_path.read_text(encoding='utf-8-sig', errors='replace')
            checksum_key = f'saved_vars_checksum__{sv_path}'
            checksum = get_checksum(content)
            auras_key = f'saved_vars_auras__{sv_path}'

            if cache.get(checksum_key) == checksum:
                logger.info(f'Loading auras from cache for {sv_path!r}')
                auras = cache[auras_key]
            else:
                with time_op(
                    lambda t: logger.debug(
                        f'Extracted {addon.name!r} auras in {t:.3f}s from {sv_path!r}'  # noqa: B023
                    )
                ):
                    from . import _custom_slpp

                    auras = addon.extract_auras(_custom_slpp.loads(f'{{ {content} }}'))

                with cache.transact():
                    cache[checksum_key] = checksum
                    cache[auras_key] = auras

            yield account_sv_path.parent.name, addon, auras


def get_build_paths(plugin_config: PluginConfig) -> _BuildPaths:
    return _BuildPaths(
        plugin_config.profile_cache_path / 'WeakAurasCompanion.zip',
        plugin_config.profile_cache_path / 'CHANGELOG.md',
        plugin_config.profile_cache_path / 'VERSION',
    )
