import pytest

from instawow import results as E
from instawow.models import Pkg
from instawow.resolvers import Defn, Strategy


@pytest.mark.asyncio
@pytest.mark.parametrize('strategy', [Strategy.default, Strategy.latest, Strategy.any_flavour])
async def test_can_resolve_curse_simple_pkgs(iw_manager, request, strategy):
    separate = Defn('curse', 'tomcats', strategy=strategy)
    retail_only = Defn('curse', 'mythic-dungeon-tools', strategy=strategy)
    classic_only = Defn('curse', 'classiccastbars', strategy=strategy)
    flavour_explosion = Defn('curse', 'elkbuffbars', strategy=strategy)

    results = await iw_manager.resolve([separate, retail_only, classic_only, flavour_explosion])
    assert type(results[separate]) is Pkg
    if iw_manager.config.is_classic:
        if strategy is Strategy.any_flavour:
            assert 'classic' not in results[separate].version
            assert type(results[retail_only]) is Pkg
        else:
            assert 'classic' in results[separate].version
            assert (
                type(results[retail_only]) is E.PkgFileUnavailable
                and results[retail_only].message
                == f"no files match classic using {strategy} strategy"
            )
        assert type(results[classic_only]) is Pkg
    else:
        assert 'classic' not in results[separate].version
        assert type(results[retail_only]) is Pkg
        if strategy is Strategy.any_flavour:
            assert type(results[classic_only]) is Pkg
        else:
            assert (
                type(results[classic_only]) is E.PkgFileUnavailable
                and results[classic_only].message
                == f"no files match retail using {strategy} strategy"
            )

    versions = {
        *request.config.cache.get('flavour_explosion', ()),
        results[flavour_explosion].version,
    }
    assert len(versions) == 1
    request.config.cache.set('flavour_explosion', tuple(versions))


@pytest.mark.asyncio
async def test_can_resolve_curse_latest_pkg(iw_manager):
    defn = Defn('curse', 'tomcats', strategy=Strategy.latest)
    results = await iw_manager.resolve([defn])
    assert results[defn].options.strategy == Strategy.latest


@pytest.mark.asyncio
async def test_can_resolve_curse_version_pinned_pkg(iw_manager):
    defn = Defn('curse', 'molinari').with_version('70300.51-Release')
    results = await iw_manager.resolve([defn])
    assert (
        results[defn].options.strategy == Strategy.version
        and results[defn].version == '70300.51-Release'
    )


@pytest.mark.asyncio
async def test_can_resolve_curse_deps(iw_manager):
    if iw_manager.config.is_classic:
        pytest.skip('no classic equivalent')

    defn = Defn('curse', 'mechagon-rare-share', strategy=Strategy.default)
    results = await iw_manager.resolve([defn], with_deps=True)
    assert ['mechagon-rare-share', 'rare-share'] == [d.slug for d in results.values()]


@pytest.mark.asyncio
async def test_can_resolve_wowi_pkgs(iw_manager):
    retail_and_classic = Defn('wowi', '13188-molinari')
    unsupported = Defn('wowi', '13188', strategy=Strategy.latest)

    results = await iw_manager.resolve([retail_and_classic, unsupported])
    assert type(results[retail_and_classic]) is Pkg
    assert (
        type(results[unsupported]) is E.PkgStrategyUnsupported
        and results[unsupported].message == "'latest' strategy is not valid for source"
    )


@pytest.mark.asyncio
async def test_can_resolve_tukui_pkgs(iw_manager):
    either = Defn('tukui', '1')
    retail_id = Defn('tukui', '-1')
    retail_slug = Defn('tukui', 'tukui')
    unsupported = Defn('tukui', '1', strategy=Strategy.latest)

    results = await iw_manager.resolve([either, retail_id, retail_slug, unsupported])
    assert type(results[either]) is Pkg
    if iw_manager.config.is_classic:
        assert results[either].name == 'Tukui'
        assert type(results[retail_id]) is E.PkgNonexistent
        assert type(results[retail_slug]) is E.PkgNonexistent
    else:
        assert results[either].name == 'MerathilisUI'
        assert type(results[retail_id]) is Pkg and results[retail_id].name == 'Tukui'
        assert type(results[retail_slug]) is Pkg and results[retail_slug].name == 'Tukui'
    assert (
        type(results[unsupported]) is E.PkgStrategyUnsupported
        and results[unsupported].message == "'latest' strategy is not valid for source"
    )


@pytest.mark.asyncio
async def test_can_resolve_github_pkgs(iw_manager):
    lib_and_nolib = Defn('github', 'AdiAddons/AdiButtonAuras')
    latest = Defn('github', 'AdiAddons/AdiButtonAuras', strategy=Strategy.latest)
    older_version = Defn('github', 'AdiAddons/AdiButtonAuras').with_version('2.1.0')
    assetless = Defn('github', 'AdiAddons/AdiButtonAuras').with_version('2.0.19')
    retail_and_classic = Defn('github', 'WeakAuras/WeakAuras2')
    releaseless = Defn('github', 'p3lim-wow/Molinari')
    missing = Defn('github', 'layday/foo-bar')

    results = await iw_manager.resolve(
        [lib_and_nolib, latest, older_version, assetless, retail_and_classic, releaseless, missing]
    )
    assert 'nolib' not in results[lib_and_nolib].download_url
    assert (
        results[latest].options.strategy == Strategy.latest
        and 'nolib' not in results[latest].download_url
    )
    assert (
        results[older_version].options.strategy == Strategy.version
        and results[older_version].version == '2.1.0'
    )
    assert type(results[assetless]) is E.PkgFileUnavailable
    assert (
        type(results[releaseless]) is E.PkgFileUnavailable
        and results[releaseless].message == 'release not found'
    )
    assert ('classic' in results[retail_and_classic].download_url) is iw_manager.config.is_classic
    assert type(results[missing]) is E.PkgNonexistent


@pytest.mark.asyncio
async def test_can_resolve_townlong_yak_pkgs(iw_manager):
    retail_and_classic = Defn('townlong-yak', 'opie')
    retail_only = Defn('townlong-yak', 'venture-plan')
    missing = Defn('townlong-yak', 'foo')
    unsupported = Defn('townlong-yak', 'foo', strategy=Strategy.latest)

    results = await iw_manager.resolve([retail_and_classic, retail_only, missing, unsupported])
    assert results[retail_and_classic].version == (
        'opie-ancient-xe-5' if iw_manager.config.is_classic else 'opie-xe-5'
    )
    if iw_manager.config.is_retail:
        assert (
            type(results[retail_only]) is Pkg
            and results[retail_only].version == 'venture-plan-4.12a'
        )
    else:
        assert type(results[retail_only]) is E.PkgFileUnavailable
    assert type(results[missing]) is E.PkgNonexistent
    assert type(results[unsupported]) is E.PkgStrategyUnsupported


@pytest.mark.asyncio
async def test_plugin_hook_dummy_pkg_can_be_resolved(iw_manager):
    pytest.importorskip('instawow_test_plugin')
    defn = Defn('me', 'bar')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is Pkg


@pytest.mark.asyncio
async def test_invalid_source_returns_invalid_exc(iw_manager):
    defn = Defn('bar', 'baz')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is E.PkgSourceInvalid
