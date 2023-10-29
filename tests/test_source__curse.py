from __future__ import annotations

import re

import pytest
from typing_extensions import assert_never
from yarl import URL

from instawow._sources.cfcore import CfCoreResolver
from instawow.common import Defn, Flavour, Strategy, StrategyValues
from instawow.manager_ctx import ManagerCtx
from instawow.pkg_management import PkgManager
from instawow.pkg_models import Pkg
from instawow.results import PkgFilesNotMatching

CURSE_IDS = {
    'big-wigs': '2382',
    'molinari': '20338',
    'adibags': '23350',
    'mythic-dungeon-tools': '288981',
    'classiccastbars': '322865',
    'elkbuffbars': '2398',
    'atlaslootclassic': '326516',
    'elvui-adibags': '333072',
    'bigwigs-voice-korean': '402180',
}


@pytest.fixture
def curse_resolver(
    iw_manager_ctx: ManagerCtx,
):
    return CfCoreResolver(iw_manager_ctx)


@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
async def test_resolve_flavourful_addon(
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', CURSE_IDS['classiccastbars'])

    result = (await curse_resolver.resolve([defn]))[defn]
    assert type(result) is Pkg


@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
async def test_resolve_classic_only_addon(
    iw_manager_ctx: ManagerCtx,
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', CURSE_IDS['atlaslootclassic'])

    result = (await curse_resolver.resolve([defn]))[defn]

    match iw_manager_ctx.config.game_flavour:
        case Flavour.VanillaClassic | Flavour.Classic:
            assert type(result) is Pkg
        case Flavour.Retail:
            assert type(result) is PkgFilesNotMatching
            assert (
                result.message
                == f'no files found for: {Strategy.AnyFlavour}=None; {Strategy.AnyReleaseType}=None; {Strategy.VersionEq}=None'
            )
        case _:
            assert_never(iw_manager_ctx.config.game_flavour)


async def test_curse_any_flavour_strategy(
    curse_resolver: CfCoreResolver,
):
    flavourful = Defn(
        'curse', CURSE_IDS['classiccastbars'], strategies=StrategyValues(any_flavour=True)
    )
    classics_only = Defn(
        'curse', CURSE_IDS['atlaslootclassic'], strategies=StrategyValues(any_flavour=True)
    )

    results = await curse_resolver.resolve([flavourful, classics_only])
    assert all(type(r) is Pkg for r in results.values())


async def test_curse_slug_match(
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', 'molinari')

    result = (await curse_resolver.resolve([defn]))[defn]
    assert type(result) is Pkg
    assert result.id == CURSE_IDS['molinari']


async def test_curse_version_pinning(
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', 'molinari', strategies=StrategyValues(version_eq='100005.97-Release'))

    result = (await curse_resolver.resolve([defn]))[defn]
    assert type(result) is Pkg
    assert result.options.version_eq is True
    assert result.version == '100005.97-Release'


async def test_curse_deps_retrieved(
    iw_manager: PkgManager,
):
    defn = Defn('curse', CURSE_IDS['bigwigs-voice-korean'])

    results = await iw_manager.resolve([defn], with_deps=True)
    assert all(type(r) is Pkg for r in results.values())
    assert {'bigwigs-voice-korean', 'big-wigs'} == {p.slug for p in results.values()}


async def test_changelog_url_format(
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', CURSE_IDS['classiccastbars'])

    result = (await curse_resolver.resolve([defn]))[defn]
    assert type(result) is Pkg
    assert re.match(
        r'https://api\.curseforge\.com/v1/mods/\d+/files/\d+/changelog',
        result.changelog_url,
    )


@pytest.mark.parametrize(
    ('url', 'extracted_alias'),
    [
        (
            'https://www.curseforge.com/wow/addons/molinari',
            'molinari',
        ),
        (
            'https://www.curseforge.com/wow/addons/molinari/download',
            'molinari',
        ),
    ],
)
def test_can_extract_alias_from_url(
    curse_resolver: CfCoreResolver,
    url: str,
    extracted_alias: str,
):
    assert curse_resolver.get_alias_from_url(URL(url)) == extracted_alias
