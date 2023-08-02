from __future__ import annotations

import logging
import re

import pytest
from aresponses import ResponsesMockServer
from attrs import evolve
from typing_extensions import assert_never
from yarl import URL

from instawow import results as R
from instawow._sources.cfcore import CfCoreResolver
from instawow._sources.github import GithubResolver
from instawow._sources.wowi import WowiResolver
from instawow.common import Defn, Flavour, Strategy, StrategyValues
from instawow.manager_ctx import ManagerCtx
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


async def test_wowi_basic(iw_manager: PkgManager):
    defn = Defn('wowi', '13188-molinari')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is Pkg


async def test_wowi_changelog_is_data_url(iw_manager: PkgManager):
    molinari = Defn('wowi', '13188-molinari')
    results = await iw_manager.resolve([molinari])
    assert results[molinari].changelog_url.startswith('data:,')


@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
async def test_tukui_basic(iw_manager: PkgManager):
    tukui_suite = Defn('tukui', 'tukui')
    elvui_suite = Defn('tukui', 'elvui')

    results = await iw_manager.resolve([tukui_suite, elvui_suite])

    assert type(results[tukui_suite]) is Pkg
    assert results[tukui_suite].name == 'Tukui'
    assert type(results[elvui_suite]) is Pkg
    assert results[elvui_suite].name == 'ElvUI'


async def test_tukui_changelog_url(iw_manager: PkgManager):
    ui_suite = Defn('tukui', 'tukui')

    results = await iw_manager.resolve([ui_suite])

    assert results[ui_suite].changelog_url == 'https://api.tukui.org/v1/changelog/tukui#20.38'


async def test_github_basic(iw_manager: PkgManager):
    release_json = Defn('github', 'nebularg/PackagerTest')
    releaseless = Defn('github', 'AdiAddons/AdiBags')
    nonexistent = Defn('github', 'layday/foobar')

    results = await iw_manager.resolve([release_json, releaseless, nonexistent])

    assert type(results[release_json]) is Pkg
    assert type(results[releaseless]) is R.PkgFilesMissing
    assert results[releaseless].message == 'release not found'
    assert type(results[nonexistent]) is R.PkgNonexistent


async def test_github_changelog_is_data_url(iw_manager: PkgManager):
    defn = Defn('github', 'p3lim-wow/Molinari')
    results = await iw_manager.resolve([defn])
    assert results[defn].changelog_url.startswith('data:,')


@pytest.mark.parametrize(
    ('iw_config_values', 'flavor', 'interface'),
    [
        (Flavour.Retail, 'mainline', 30400),
        (Flavour.Classic, 'wrath', 90207),
        (Flavour.VanillaClassic, 'classic', 90207),
    ],
    indirect=('iw_config_values',),
)
@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [
        {
            URL('//api.github.com/repos/nebularg/PackagerTest'),
            URL('//api.github.com/repos/nebularg/PackagerTest/releases?per_page=10'),
        }
    ],
    indirect=True,
)
async def test_github_flavor_and_interface_mismatch(
    caplog: pytest.LogCaptureFixture,
    aresponses: ResponsesMockServer,
    iw_manager: PkgManager,
    flavor: str,
    interface: int,
):
    aresponses.add(
        'api.github.com',
        re.compile(r'^/repos/nebularg/PackagerTest/releases/assets/'),
        'GET',
        {
            'releases': [
                {
                    'filename': 'TestGit-v1.9.7.zip',
                    'nolib': False,
                    'metadata': [{'flavor': flavor, 'interface': interface}],
                }
            ]
        },
    )

    defn = Defn('github', 'nebularg/PackagerTest')
    results = await iw_manager.resolve([defn])
    mismatch_result = results[defn]

    assert type(mismatch_result) is R.PkgFilesNotMatching

    (log_record,) = caplog.record_tuples
    assert log_record == (
        'instawow._sources.github',
        logging.INFO,
        f'interface number "{interface}" and flavor "{flavor}" mismatch',
    )


@pytest.mark.parametrize('resolver', ManagerCtx.RESOLVERS)
async def test_unsupported_strategies(iw_manager: PkgManager, resolver: Resolver):
    if resolver.metadata.id not in iw_manager.ctx.resolvers:
        pytest.skip('resolver not loaded')

    defn = Defn(resolver.metadata.id, 'foo')
    for strategy in {
        Strategy.AnyFlavour,
        Strategy.AnyReleaseType,
    } - resolver.metadata.strategies:
        strategy_defn = evolve(defn, strategies=StrategyValues(**{strategy: True}))

        results = await iw_manager.resolve([strategy_defn])

        assert type(results[strategy_defn]) is R.PkgStrategiesUnsupported
        assert results[strategy_defn].message == f'strategies are not valid for source: {strategy}'


@pytest.mark.parametrize(
    ('resolver', 'url', 'extracted_alias'),
    [
        (CfCoreResolver, 'https://www.curseforge.com/wow/addons/molinari', 'molinari'),
        (CfCoreResolver, 'https://www.curseforge.com/wow/addons/molinari/download', 'molinari'),
        (WowiResolver, 'https://www.wowinterface.com/downloads/landing.php?fileid=13188', '13188'),
        (WowiResolver, 'https://wowinterface.com/downloads/landing.php?fileid=13188', '13188'),
        (WowiResolver, 'https://www.wowinterface.com/downloads/fileinfo.php?id=13188', '13188'),
        (WowiResolver, 'https://wowinterface.com/downloads/fileinfo.php?id=13188', '13188'),
        (WowiResolver, 'https://www.wowinterface.com/downloads/download13188-Molinari', '13188'),
        (WowiResolver, 'https://wowinterface.com/downloads/download13188-Molinari', '13188'),
        (WowiResolver, 'https://www.wowinterface.com/downloads/info13188-Molinari.html', '13188'),
        (WowiResolver, 'https://wowinterface.com/downloads/info13188-Molinari.html', '13188'),
        (WowiResolver, 'https://www.wowinterface.com/downloads/info13188', '13188'),
        (WowiResolver, 'https://wowinterface.com/downloads/info13188', '13188'),
        (
            GithubResolver,
            'https://github.com/AdiAddons/AdiButtonAuras',
            'AdiAddons/AdiButtonAuras',
        ),
        (
            GithubResolver,
            'https://github.com/AdiAddons/AdiButtonAuras/releases',
            'AdiAddons/AdiButtonAuras',
        ),
    ],
)
def test_get_alias_from_url(resolver: Resolver, url: str, extracted_alias: str):
    assert resolver.get_alias_from_url(URL(url)) == extracted_alias
