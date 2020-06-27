import pytest

import instawow.exceptions as E
from instawow.models import Pkg
from instawow.resolvers import Defn, Strategies


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'strategy', [Strategies.default, Strategies.latest, Strategies.any_flavour]
)
async def test_resolve_curse_pkgs(manager, request, strategy):
    results = await manager.resolve(
        [
            Defn('curse', 'tomcats', strategy),
            Defn('curse', 'method-dungeon-tools', strategy),
            Defn('curse', 'classiccastbars', strategy),
            Defn('curse', 'elkbuffbars', strategy),
        ]
    )
    separate, retail_only, classic_only, flavour_explosion = results.values()

    assert isinstance(separate, Pkg)
    if manager.config.is_classic:
        if strategy is Strategies.any_flavour:
            assert 'classic' not in separate.version
            assert isinstance(retail_only, Pkg)
        else:
            assert 'classic' in separate.version
            assert (
                isinstance(retail_only, E.PkgFileUnavailable)
                and retail_only.message
                == f"no files compatible with classic using '{strategy.name}' strategy"
            )
        assert isinstance(classic_only, Pkg)
    else:
        assert 'classic' not in separate.version
        assert isinstance(retail_only, Pkg)
        if strategy is Strategies.any_flavour:
            assert isinstance(classic_only, Pkg)
        else:
            assert (
                isinstance(classic_only, E.PkgFileUnavailable)
                and classic_only.message
                == f"no files compatible with retail using '{strategy.name}' strategy"
            )

    versions = {*request.config.cache.get('flavour_explosion', ()), flavour_explosion.version}
    assert len(versions) == 1
    request.config.cache.set('flavour_explosion', tuple(versions))


@pytest.mark.asyncio
async def test_resolve_curse_latest_pkg(manager):
    (latest,) = (await manager.resolve([Defn('curse', 'tomcats', Strategies.latest)])).values()
    assert isinstance(latest, Pkg)


@pytest.mark.asyncio
async def test_resolve_curse_deps(manager):
    if manager.config.is_classic:
        pytest.skip('no classic equivalent')

    defns = [Defn('curse', 'mechagon-rare-share', Strategies.default)]
    with_deps = await manager.resolve(defns, with_deps=True)
    assert ['mechagon-rare-share', 'rare-share'] == [d.slug for d in with_deps.values()]


@pytest.mark.asyncio
async def test_resolve_tukui_pkgs(manager):
    results = await manager.resolve(
        [
            Defn('tukui', '1'),
            Defn('tukui', '-1'),
            Defn('tukui', 'tukui'),
            Defn('tukui', '1', Strategies.latest),
        ]
    )
    either, retail_id, retail_slug, invalid = results.values()

    assert isinstance(either, Pkg)
    if manager.config.is_classic:
        assert either.name == 'Tukui'
        assert isinstance(retail_id, E.PkgNonexistent)
        assert isinstance(retail_slug, E.PkgNonexistent)
    else:
        assert either.name == 'MerathilisUI'
        assert isinstance(retail_id, Pkg) and retail_id.name == 'Tukui'
        assert isinstance(retail_slug, Pkg) and retail_slug.name == 'Tukui'
    assert (
        isinstance(invalid, E.PkgStrategyUnsupported)
        and invalid.message == "'latest' strategy is not valid for source"
    )


@pytest.mark.asyncio
async def test_resolve_wowi_pkgs(manager):
    results = await manager.resolve(
        [Defn('wowi', '13188-molinari'), Defn('wowi', '13188', Strategies.latest)]
    )
    either, invalid = results.values()

    assert isinstance(either, Pkg)
    assert (
        isinstance(invalid, E.PkgStrategyUnsupported)
        and invalid.message == "'latest' strategy is not valid for source"
    )
