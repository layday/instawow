from __future__ import annotations

import re

import pytest
from yarl import URL

from instawow import results as R
from instawow.common import Flavour, Strategy
from instawow.manager import Manager
from instawow.models import Pkg
from instawow.resolvers import (
    CurseResolver,
    Defn,
    GithubResolver,
    Resolver,
    TukuiResolver,
    WowiResolver,
)
from instawow.utils import evolve_model_obj


@pytest.mark.parametrize('strategy', [Strategy.default, Strategy.latest])
async def test_curse_simple_strategies(iw_manager: Manager, strategy: Strategy):
    flavourful = Defn('curse', 'molinari', strategy=strategy)
    retail_only = Defn('curse', 'mythic-dungeon-tools', strategy=strategy)
    classic_only = Defn('curse', 'classiccastbars', strategy=strategy)

    results = await iw_manager.resolve([flavourful, retail_only, classic_only])

    if iw_manager.config.game_flavour is Flavour.vanilla_classic:
        assert results[flavourful].version.endswith('Release-classic')
        assert (
            type(results[retail_only]) is R.PkgFileUnavailable
            and results[retail_only].message
            == f"no files matching vanilla_classic using {strategy} strategy"
        )
        assert type(results[classic_only]) is Pkg

    elif iw_manager.config.game_flavour is Flavour.burning_crusade_classic:
        assert results[flavourful].version.endswith('Release-bcc')
        assert (
            type(results[retail_only]) is R.PkgFileUnavailable
            and results[retail_only].message
            == f"no files matching classic using {strategy} strategy"
        )
        assert type(results[classic_only]) is Pkg

    elif iw_manager.config.game_flavour is Flavour.retail:
        assert results[flavourful].version.endswith('Release')
        assert type(results[retail_only]) is Pkg
        assert (
            type(results[classic_only]) is R.PkgFileUnavailable
            and results[classic_only].message
            == f"no files matching retail using {strategy} strategy"
        )

    else:
        assert False


async def test_curse_any_flavour_strategy(iw_manager: Manager):
    flavourful = Defn('curse', 'molinari', strategy=Strategy.any_flavour)
    retail_only = Defn('curse', 'mythic-dungeon-tools', strategy=Strategy.any_flavour)
    classic_only = Defn('curse', 'classiccastbars', strategy=Strategy.any_flavour)

    results = await iw_manager.resolve([flavourful, retail_only, classic_only])
    assert all(type(r) is Pkg for r in results.values())


async def test_curse_version_pinning(iw_manager: Manager):
    defn = Defn('curse', 'molinari').with_version('70300.51-Release')
    results = await iw_manager.resolve([defn])
    assert (
        results[defn].options.strategy == Strategy.version
        and results[defn].version == '70300.51-Release'
    )


@pytest.mark.parametrize(
    'iw_config_values',
    [Flavour.retail],
    indirect=True,
)
async def test_curse_deps_retrieved(iw_manager: Manager):
    defn = Defn('curse', 'bigwigs-voice-korean')

    results = await iw_manager.resolve([defn], with_deps=True)
    assert {'bigwigs-voice-korean', 'big-wigs'} == {d.slug for d in results.values()}


async def test_curse_changelog_is_url(iw_manager: Manager):
    molinari = Defn('curse', 'molinari')

    results = await iw_manager.resolve([molinari])
    assert re.match(
        r'https://addons-ecs\.forgesvc\.net/api/v2/addon/\d+/file/\d+/changelog',
        results[molinari].changelog_url,
    )


async def test_wowi_basic(iw_manager: Manager):
    defn = Defn('wowi', '13188-molinari')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is Pkg


async def test_wowi_changelog_is_data_url(iw_manager: Manager):
    molinari = Defn('wowi', '13188-molinari')
    results = await iw_manager.resolve([molinari])
    assert results[molinari].changelog_url.startswith('data:,')


async def test_tukui_basic(iw_manager: Manager):
    regular = Defn('tukui', '1')
    ui_suite = Defn('tukui', '-1')

    results = await iw_manager.resolve([regular, ui_suite])

    if iw_manager.config.game_flavour is Flavour.retail:
        assert type(results[regular]) is Pkg and results[regular].name == 'MerathilisUI'
        assert type(results[ui_suite]) is Pkg and results[ui_suite].name == 'Tukui'
    else:
        assert type(results[regular]) is Pkg and results[regular].name == 'Tukui'
        assert type(results[ui_suite]) is R.PkgNonexistent


@pytest.mark.parametrize(
    'iw_config_values',
    [Flavour.retail],
    indirect=True,
)
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

    if iw_manager.config.game_flavour is Flavour.retail:
        assert results[ui_suite].changelog_url == 'https://www.tukui.org/ui/tukui/changelog#20.23'
    assert results[regular_addon].changelog_url.startswith('data:,')


async def test_github_basic(iw_manager: Manager):
    release_json = Defn('github', 'nebularg/PackagerTest')
    releaseless = Defn('github', 'AdiAddons/AdiBags')
    nonexistent = Defn('github', 'layday/foobar')

    results = await iw_manager.resolve([release_json, releaseless, nonexistent])

    release_json_result = results[release_json]
    if iw_manager.config.game_flavour is Flavour.burning_crusade_classic:
        assert type(release_json_result) is R.PkgFileUnavailable
    else:
        assert type(release_json_result) is Pkg
        if iw_manager.config.game_flavour is Flavour.vanilla_classic:
            assert 'classic' in release_json_result.download_url
        assert 'nolib' not in release_json_result.download_url
    releaseless_result = results[releaseless]
    assert (
        type(releaseless_result) is R.PkgFileUnavailable
        and releaseless_result.message == 'release not found'
    )
    assert type(results[nonexistent]) is R.PkgNonexistent


async def test_github_changelog_is_data_url(iw_manager: Manager):
    defn = Defn('github', 'p3lim-wow/Molinari')
    results = await iw_manager.resolve([defn])
    assert results[defn].changelog_url.startswith('data:,')


@pytest.mark.parametrize('resolver', Manager.RESOLVERS)
async def test_unsupported_strategies(iw_manager: Manager, resolver: Resolver):
    defn = Defn(resolver.source, 'foo')
    for strategy in set(Strategy) - {Strategy.version} - resolver.strategies:
        strategy_defn = evolve_model_obj(defn, strategy=strategy)

        results = await iw_manager.resolve([strategy_defn])

        assert (
            type(results[strategy_defn]) is R.PkgStrategyUnsupported
            and results[strategy_defn].message == f"'{strategy}' strategy is not valid for source"
        )


@pytest.mark.parametrize(
    ('resolver', 'url', 'extracted_alias'),
    [
        (CurseResolver, 'https://www.curseforge.com/wow/addons/molinari', 'molinari'),
        (CurseResolver, 'https://www.curseforge.com/wow/addons/molinari/download', 'molinari'),
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
        (TukuiResolver, 'https://www.tukui.org/classic-tbc-addons.php?id=1', '1'),
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
