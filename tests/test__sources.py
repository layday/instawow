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
from instawow._sources.tukui import TukuiResolver
from instawow._sources.wowi import WowiResolver
from instawow.common import Defn, Flavour, Strategy, StrategyValues
from instawow.manager import Manager
from instawow.models import Pkg
from instawow.resolvers import Resolver


@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
async def test_curse_simple_strategies(iw_manager: Manager):
    flavourful = Defn('curse', 'classiccastbars')
    retail_only = Defn('curse', 'mythic-dungeon-tools')

    results = await iw_manager.resolve([flavourful, retail_only])

    assert type(results[flavourful]) is Pkg

    if (
        iw_manager.config.game_flavour is Flavour.vanilla_classic
        or iw_manager.config.game_flavour is Flavour.classic
    ):
        assert type(results[retail_only]) is R.PkgFilesNotMatching
        assert (
            results[retail_only].message
            == 'no files found for: any_flavour=None; any_release_type=None; version_eq=None'
        )
    elif iw_manager.config.game_flavour is Flavour.retail:
        assert type(results[retail_only]) is Pkg
    else:
        assert_never(iw_manager.config.game_flavour)


async def test_curse_any_flavour_strategy(iw_manager: Manager):
    flavourful = Defn('curse', 'classiccastbars', strategies=StrategyValues(any_flavour=True))
    retail_only = Defn(
        'curse', 'mythic-dungeon-tools', strategies=StrategyValues(any_flavour=True)
    )

    results = await iw_manager.resolve([flavourful, retail_only])
    assert all(type(r) is Pkg for r in results.values())


async def test_curse_version_pinning(iw_manager: Manager):
    defn = Defn('curse', 'molinari', strategies=StrategyValues(version_eq='80000.58-Release'))
    results = await iw_manager.resolve([defn])
    assert results[defn].options.version_eq is True
    assert results[defn].version == '80000.58-Release'


async def test_curse_deps_retrieved(iw_manager: Manager):
    defn = Defn('curse', 'bigwigs-voice-korean')

    results = await iw_manager.resolve([defn], with_deps=True)
    assert {'bigwigs-voice-korean', 'big-wigs'} == {d.slug for d in results.values()}


async def test_curse_changelog_is_url(iw_manager: Manager):
    classiccastbars = Defn('curse', 'classiccastbars')

    results = await iw_manager.resolve([classiccastbars])
    assert re.match(
        r'https://api\.curseforge\.com/v1/mods/\d+/files/\d+/changelog',
        results[classiccastbars].changelog_url,
    )


async def test_wowi_basic(iw_manager: Manager):
    defn = Defn('wowi', '13188-molinari')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is Pkg


async def test_wowi_changelog_is_data_url(iw_manager: Manager):
    molinari = Defn('wowi', '13188-molinari')
    results = await iw_manager.resolve([molinari])
    assert results[molinari].changelog_url.startswith('data:,')


@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
async def test_tukui_basic(iw_manager: Manager):
    regular_addon = Defn('tukui', '1' if iw_manager.config.game_flavour is Flavour.retail else '2')
    tukui_suite = Defn('tukui', '-1')
    elvui_suite = Defn('tukui', '-2')

    results = await iw_manager.resolve([regular_addon, tukui_suite, elvui_suite])

    assert type(results[regular_addon]) is Pkg
    assert (
        results[regular_addon].name == 'MerathilisUI'
        if iw_manager.config.game_flavour is Flavour.retail
        else 'ElvUI'
    )
    assert type(results[tukui_suite]) is Pkg
    assert results[tukui_suite].name == 'Tukui'
    assert type(results[elvui_suite]) is Pkg
    assert results[elvui_suite].name == 'ElvUI'


async def test_tukui_ui_suite_aliases_for_retail(iw_manager: Manager):
    tukui_id = Defn('tukui', '-1')
    tukui_slug = Defn('tukui', 'tukui')
    elvui_id = Defn('tukui', '-2')
    elvui_slug = Defn('tukui', 'elvui')

    results = await iw_manager.resolve([tukui_id, tukui_slug, elvui_id, elvui_slug])

    assert results[tukui_id].id == results[tukui_slug].id
    assert results[elvui_id].id == results[elvui_slug].id


async def test_tukui_changelog_url_for_addon_type(iw_manager: Manager):
    ui_suite = Defn('tukui', '-1')
    regular_addon = Defn('tukui', '1')

    results = await iw_manager.resolve([ui_suite, regular_addon])

    assert results[ui_suite].changelog_url == 'https://www.tukui.org/ui/tukui/changelog#20.28'
    assert results[regular_addon].changelog_url.startswith('data:,')


async def test_github_basic(iw_manager: Manager):
    release_json = Defn('github', 'nebularg/PackagerTest')
    releaseless = Defn('github', 'AdiAddons/AdiBags')
    nonexistent = Defn('github', 'layday/foobar')

    results = await iw_manager.resolve([release_json, releaseless, nonexistent])

    assert type(results[release_json]) is Pkg
    assert type(results[releaseless]) is R.PkgFilesMissing
    assert results[releaseless].message == 'release not found'
    assert type(results[nonexistent]) is R.PkgNonexistent


async def test_github_changelog_is_data_url(iw_manager: Manager):
    defn = Defn('github', 'p3lim-wow/Molinari')
    results = await iw_manager.resolve([defn])
    assert results[defn].changelog_url.startswith('data:,')


@pytest.mark.parametrize(
    ('iw_config_values', 'flavor', 'interface'),
    [
        (Flavour.retail, 'mainline', 30400),
        (Flavour.classic, 'wrath', 90207),
        (Flavour.vanilla_classic, 'classic', 90207),
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
    iw_manager: Manager,
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


@pytest.mark.parametrize('resolver', Manager.RESOLVERS)
async def test_unsupported_strategies(iw_manager: Manager, resolver: Resolver):
    if resolver.metadata.id not in iw_manager.resolvers:
        pytest.skip('resolver not loaded')

    defn = Defn(resolver.metadata.id, 'foo')
    for strategy in {
        Strategy.any_flavour,
        Strategy.any_release_type,
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
        (TukuiResolver, 'https://www.tukui.org/download.php?ui=tukui', 'tukui'),
        (TukuiResolver, 'https://www.tukui.org/addons.php?id=1', '1'),
        (TukuiResolver, 'https://www.tukui.org/classic-addons.php?id=1', '1'),
        (TukuiResolver, 'https://www.tukui.org/classic-wotlk-addons.php?id=1', '1'),
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
