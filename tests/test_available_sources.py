import re

import pytest

from instawow import results as R
from instawow.common import Strategy
from instawow.config import Flavour
from instawow.models import Pkg
from instawow.resolvers import Defn


@pytest.mark.asyncio
@pytest.mark.parametrize('strategy', [Strategy.default, Strategy.latest, Strategy.any_flavour])
async def test_curse_common_strategies(iw_manager, request, strategy):
    retail_and_vanilla_classic_files = Defn('curse', 'molinari', strategy=strategy)
    retail_only_file = Defn('curse', 'mythic-dungeon-tools', strategy=strategy)
    classic_only_file = Defn('curse', 'classiccastbars', strategy=strategy)
    multiflavour_file = Defn('curse', 'elkbuffbars', strategy=strategy)

    results = await iw_manager.resolve(
        [retail_and_vanilla_classic_files, retail_only_file, classic_only_file, multiflavour_file]
    )
    if iw_manager.config.game_flavour is Flavour.vanilla_classic:
        if strategy is Strategy.any_flavour:
            assert type(results[retail_only_file]) is Pkg
        else:
            assert 'classic' in results[retail_and_vanilla_classic_files].version
            assert (
                type(results[retail_only_file]) is R.PkgFileUnavailable
                and results[retail_only_file].message
                == f"no files match vanilla_classic using {strategy} strategy"
            )
        assert type(results[classic_only_file]) is Pkg
    elif iw_manager.config.game_flavour is Flavour.retail:
        assert type(results[retail_only_file]) is Pkg
        if strategy is Strategy.any_flavour:
            assert type(results[classic_only_file]) is Pkg
        else:
            assert 'classic' not in results[retail_and_vanilla_classic_files].version
            assert (
                type(results[classic_only_file]) is R.PkgFileUnavailable
                and results[classic_only_file].message
                == f"no files match retail using {strategy} strategy"
            )


@pytest.mark.asyncio
async def test_curse_version_pinning(iw_manager):
    defn = Defn('curse', 'molinari').with_version('70300.51-Release')
    results = await iw_manager.resolve([defn])
    assert (
        results[defn].options.strategy == Strategy.version
        and results[defn].version == '70300.51-Release'
    )


@pytest.mark.asyncio
async def test_curse_deps_are_found(iw_manager):
    defn = Defn('curse', 'bigwigs-voice-korean')

    if iw_manager.config.game_flavour is not Flavour.retail:
        pytest.skip(f'{defn} is only available for retail')

    results = await iw_manager.resolve([defn], with_deps=True)
    assert ['bigwigs-voice-korean', 'big-wigs'] == [d.slug for d in results.values()]


@pytest.mark.asyncio
async def test_curse_changelog_is_url(iw_manager):
    molinari = Defn('curse', 'molinari')

    results = await iw_manager.resolve([molinari])
    assert re.match(
        r'https://addons-ecs\.forgesvc\.net/api/v2/addon/\d+/file/\d+/changelog',
        results[molinari].changelog_url,
    )


@pytest.mark.asyncio
async def test_wowi(iw_manager):
    retail_and_classic = Defn('wowi', '13188-molinari')
    unsupported_strategy = Defn('wowi', '13188', strategy=Strategy.latest)

    results = await iw_manager.resolve([retail_and_classic, unsupported_strategy])
    assert type(results[retail_and_classic]) is Pkg
    assert (
        type(results[unsupported_strategy]) is R.PkgStrategyUnsupported
        and results[unsupported_strategy].message == "'latest' strategy is not valid for source"
    )


@pytest.mark.asyncio
async def test_wowi_changelog_is_data_url(iw_manager):
    molinari = Defn('wowi', '13188-molinari')
    results = await iw_manager.resolve([molinari])
    assert results[molinari].changelog_url.startswith('data:,')


@pytest.mark.asyncio
async def test_tukui(iw_manager):
    regular_addon = Defn('tukui', '1')
    ui_suite = Defn('tukui', '-1')
    ui_suite_with_slug = Defn('tukui', 'tukui')
    unsupported_strategy = Defn('tukui', '1', strategy=Strategy.latest)

    results = await iw_manager.resolve(
        [regular_addon, ui_suite, ui_suite_with_slug, unsupported_strategy]
    )

    if iw_manager.config.game_flavour is Flavour.retail:
        assert (
            type(results[regular_addon]) is Pkg and results[regular_addon].name == 'MerathilisUI'
        )
        assert type(results[ui_suite]) is Pkg and results[ui_suite].name == 'Tukui'
        assert (
            type(results[ui_suite_with_slug]) is Pkg
            and results[ui_suite_with_slug].name == 'Tukui'
        )
    else:
        assert type(results[regular_addon]) is Pkg and results[regular_addon].name == 'Tukui'
        assert type(results[ui_suite]) is R.PkgNonexistent
        assert type(results[ui_suite_with_slug]) is R.PkgNonexistent
    assert (
        type(results[unsupported_strategy]) is R.PkgStrategyUnsupported
        and results[unsupported_strategy].message == "'latest' strategy is not valid for source"
    )


@pytest.mark.asyncio
async def test_tukui_changelog_url_varies_by_addon_type(iw_manager):
    ui_suite = Defn('tukui', '-1')
    regular_addon = Defn('tukui', '1')
    results = await iw_manager.resolve([ui_suite, regular_addon])
    if iw_manager.config.game_flavour is Flavour.retail:
        assert results[ui_suite].changelog_url == 'https://www.tukui.org/ui/tukui/changelog#20.17'
    assert results[regular_addon].changelog_url.startswith('data:,')


@pytest.mark.asyncio
async def test_github(iw_manager):
    release_json = Defn('github', 'nebularg/PackagerTest')
    legacy_lib_and_nolib = Defn('github', 'AdiAddons/AdiButtonAuras')
    legacy_latest = Defn('github', 'AdiAddons/AdiButtonAuras', strategy=Strategy.latest)
    legacy_older_version = Defn('github', 'AdiAddons/AdiButtonAuras').with_version('2.1.0')
    legacy_assetless = Defn('github', 'AdiAddons/AdiButtonAuras').with_version('2.0.19')
    legacy_retail_and_classic = Defn('github', 'p3lim-wow/Molinari')
    releaseless = Defn('github', 'AdiAddons/AdiBags')
    nonexistent = Defn('github', 'layday/foobar')

    results = await iw_manager.resolve(
        [
            release_json,
            legacy_lib_and_nolib,
            legacy_latest,
            legacy_older_version,
            legacy_assetless,
            legacy_retail_and_classic,
            releaseless,
            nonexistent,
        ]
    )
    assert ('classic' in results[release_json].download_url) is (
        iw_manager.config.game_flavour is Flavour.vanilla_classic
    )
    assert 'nolib' not in results[release_json].download_url
    assert 'nolib' not in results[legacy_lib_and_nolib].download_url
    assert (
        results[legacy_latest].options.strategy == Strategy.latest
        and 'nolib' not in results[legacy_latest].download_url
    )
    assert (
        results[legacy_older_version].options.strategy == Strategy.version
        and results[legacy_older_version].version == '2.1.0'
    )
    assert type(results[legacy_assetless]) is R.PkgFileUnavailable
    assert ('classic' in results[legacy_retail_and_classic].download_url) is (
        iw_manager.config.game_flavour is Flavour.vanilla_classic
    )
    assert (
        type(results[releaseless]) is R.PkgFileUnavailable
        and results[releaseless].message == 'release not found'
    )
    assert type(results[nonexistent]) is R.PkgNonexistent


@pytest.mark.asyncio
async def test_github_changelog_is_data_url(iw_manager):
    adibuttonauras = Defn('github', 'AdiAddons/AdiButtonAuras')
    results = await iw_manager.resolve([adibuttonauras])
    assert results[adibuttonauras].changelog_url.startswith('data:,')
