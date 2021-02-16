import pytest

from instawow import results as E
from instawow.models import Pkg
from instawow.resolvers import Defn, Strategy


@pytest.fixture(autouse=True)
def mock(mock_all):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize('strategy', [Strategy.default, Strategy.latest, Strategy.any_flavour])
async def test_resolve_curse_simple_pkgs(iw_manager, request, strategy):
    results = await iw_manager.resolve(
        [
            Defn('curse', 'tomcats', strategy=strategy),
            Defn('curse', 'mythic-dungeon-tools', strategy=strategy),
            Defn('curse', 'classiccastbars', strategy=strategy),
            Defn('curse', 'elkbuffbars', strategy=strategy),
        ]
    )
    separate, retail_only, classic_only, flavour_explosion = results.values()

    assert type(separate) is Pkg
    if iw_manager.config.is_classic:
        if strategy is Strategy.any_flavour:
            assert 'classic' not in separate.version
            assert type(retail_only) is Pkg
        else:
            assert 'classic' in separate.version
            assert (
                type(retail_only) is E.PkgFileUnavailable
                and retail_only.message == f"no files match classic using {strategy} strategy"
            )
        assert type(classic_only) is Pkg
    else:
        assert 'classic' not in separate.version
        assert type(retail_only) is Pkg
        if strategy is Strategy.any_flavour:
            assert type(classic_only) is Pkg
        else:
            assert (
                type(classic_only) is E.PkgFileUnavailable
                and classic_only.message == f"no files match retail using {strategy} strategy"
            )

    versions = {*request.config.cache.get('flavour_explosion', ()), flavour_explosion.version}
    assert len(versions) == 1
    request.config.cache.set('flavour_explosion', tuple(versions))


@pytest.mark.asyncio
async def test_resolve_curse_latest_pkg(iw_manager):
    (latest_pkg,) = (
        await iw_manager.resolve([Defn('curse', 'tomcats', strategy=Strategy.latest)])
    ).values()
    assert latest_pkg.options.strategy == Strategy.latest


@pytest.mark.asyncio
async def test_resolve_curse_versioned_pkg(iw_manager):
    (versioned_pkg,) = (
        await iw_manager.resolve([Defn('curse', 'molinari').with_version('70300.51-Release')])
    ).values()
    assert (
        versioned_pkg.options.strategy == Strategy.version
        and versioned_pkg.version == '70300.51-Release'
    )


@pytest.mark.asyncio
async def test_resolve_curse_deps(iw_manager):
    if iw_manager.config.is_classic:
        pytest.skip('no classic equivalent')

    defns = [Defn('curse', 'mechagon-rare-share', strategy=Strategy.default)]
    with_deps = await iw_manager.resolve(defns, with_deps=True)
    assert ['mechagon-rare-share', 'rare-share'] == [d.slug for d in with_deps.values()]


@pytest.mark.asyncio
async def test_resolve_wowi_pkgs(iw_manager):
    results = await iw_manager.resolve(
        [
            Defn('wowi', '13188-molinari'),
            Defn('wowi', '13188', strategy=Strategy.latest),
        ]
    )
    either, invalid = results.values()

    assert type(either) is Pkg
    assert (
        type(invalid) is E.PkgStrategyUnsupported
        and invalid.message == "'latest' strategy is not valid for source"
    )


@pytest.mark.asyncio
async def test_resolve_tukui_pkgs(iw_manager):
    results = await iw_manager.resolve(
        [
            Defn('tukui', '1'),
            Defn('tukui', '-1'),
            Defn('tukui', 'tukui'),
            Defn('tukui', '1', strategy=Strategy.latest),
        ]
    )
    either, retail_id, retail_slug, invalid = results.values()

    assert type(either) is Pkg
    if iw_manager.config.is_classic:
        assert either.name == 'Tukui'
        assert type(retail_id) is E.PkgNonexistent
        assert type(retail_slug) is E.PkgNonexistent
    else:
        assert either.name == 'MerathilisUI'
        assert type(retail_id) is Pkg and retail_id.name == 'Tukui'
        assert type(retail_slug) is Pkg and retail_slug.name == 'Tukui'
    assert (
        type(invalid) is E.PkgStrategyUnsupported
        and invalid.message == "'latest' strategy is not valid for source"
    )


@pytest.mark.asyncio
async def test_resolve_github_pkgs(iw_manager):
    defns = [
        Defn('github', 'AdiAddons/AdiButtonAuras'),
        Defn('github', 'AdiAddons/AdiButtonAuras', strategy=Strategy.latest),
        Defn('github', 'AdiAddons/AdiButtonAuras').with_version('2.1.0'),
        Defn('github', 'AdiAddons/AdiButtonAuras').with_version('2.0.19'),
        Defn('github', 'WeakAuras/WeakAuras2'),
        Defn('github', 'p3lim-wow/Molinari'),
        Defn('github', 'layday/foo-bar'),
    ]
    [
        lib_and_nolib,
        latest,
        older_version,
        assetless,
        retail_and_classic,
        releaseless,
        missing,
    ] = (await iw_manager.resolve(defns)).values()
    assert 'nolib' not in lib_and_nolib.download_url
    assert latest.options.strategy == Strategy.latest and 'nolib' not in latest.download_url
    assert older_version.options.strategy == Strategy.version and older_version.version == '2.1.0'
    assert type(assetless) is E.PkgFileUnavailable
    assert type(releaseless) is E.PkgFileUnavailable and releaseless.message == 'release not found'
    assert ('classic' in retail_and_classic.download_url) is iw_manager.config.is_classic
    assert type(missing) is E.PkgNonexistent


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
