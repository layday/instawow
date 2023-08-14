from __future__ import annotations

import re

import pytest
from typing_extensions import assert_never
from yarl import URL

from instawow import results as R
from instawow._sources.cfcore import CfCoreResolver
from instawow.common import Defn, Flavour, StrategyValues
from instawow.pkg_management import PkgManager
from instawow.pkg_models import Pkg
from instawow.resolvers import Resolver

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


@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
async def test_curse_simple_strategies(iw_manager: PkgManager):
    flavourful = Defn('curse', CURSE_IDS['classiccastbars'])
    classics_only = Defn('curse', CURSE_IDS['atlaslootclassic'])

    results = await iw_manager.resolve([flavourful, classics_only])

    assert type(results[flavourful]) is Pkg

    if iw_manager.ctx.config.game_flavour in {Flavour.VanillaClassic, Flavour.Classic}:
        assert type(results[classics_only]) is Pkg
    elif iw_manager.ctx.config.game_flavour is Flavour.Retail:
        assert type(results[classics_only]) is R.PkgFilesNotMatching
        assert (
            results[classics_only].message
            == 'no files found for: any_flavour=None; any_release_type=None; version_eq=None'
        )
    else:
        assert_never(iw_manager.ctx.config.game_flavour)


async def test_curse_any_flavour_strategy(iw_manager: PkgManager):
    flavourful = Defn(
        'curse', CURSE_IDS['classiccastbars'], strategies=StrategyValues(any_flavour=True)
    )
    classics_only = Defn(
        'curse', CURSE_IDS['atlaslootclassic'], strategies=StrategyValues(any_flavour=True)
    )

    results = await iw_manager.resolve([flavourful, classics_only])
    assert all(type(r) is Pkg for r in results.values())


async def test_curse_slug_match(iw_manager: PkgManager):
    defn = Defn('curse', 'molinari')
    results = await iw_manager.resolve([defn])
    assert results[defn].id == CURSE_IDS['molinari']


async def test_curse_version_pinning(iw_manager: PkgManager):
    defn = Defn('curse', 'molinari', strategies=StrategyValues(version_eq='100005.97-Release'))
    results = await iw_manager.resolve([defn])
    assert results[defn].options.version_eq is True
    assert results[defn].version == '100005.97-Release'


async def test_curse_deps_retrieved(iw_manager: PkgManager):
    defn = Defn('curse', CURSE_IDS['bigwigs-voice-korean'])

    results = await iw_manager.resolve([defn], with_deps=True)
    assert {'bigwigs-voice-korean', 'big-wigs'} == {d.slug for d in results.values()}


async def test_curse_changelog_is_url(iw_manager: PkgManager):
    classiccastbars = Defn('curse', CURSE_IDS['classiccastbars'])

    results = await iw_manager.resolve([classiccastbars])
    assert re.match(
        r'https://api\.curseforge\.com/v1/mods/\d+/files/\d+/changelog',
        results[classiccastbars].changelog_url,
    )


@pytest.mark.parametrize(
    ('resolver', 'url', 'extracted_alias'),
    [
        (CfCoreResolver, 'https://www.curseforge.com/wow/addons/molinari', 'molinari'),
        (CfCoreResolver, 'https://www.curseforge.com/wow/addons/molinari/download', 'molinari'),
    ],
)
def test_get_alias_from_url(resolver: Resolver, url: str, extracted_alias: str):
    assert resolver.get_alias_from_url(URL(url)) == extracted_alias
