import pytest

import instawow.exceptions as E
from instawow.models import Pkg
from instawow.resolvers import Defn, Strategies


@pytest.mark.asyncio
@pytest.mark.parametrize('strategy', [Strategies.default, Strategies.latest])
async def test_curse(manager, request, strategy):
    (separate, retail_only, classic_only, flavour_explosion) = (
        await manager.resolve([Defn('curse', 'tomcats', strategy),
                               Defn('curse', 'method-dungeon-tools', strategy),
                               Defn('curse', 'classiccastbars', strategy),
                               Defn('curse', 'elkbuffbars', strategy)])).values()

    assert isinstance(separate, Pkg)
    if manager.config.is_classic:
        assert 'classic' in separate.version
        assert (isinstance(retail_only, E.PkgFileUnavailable)
                and retail_only.message == f"no files compatible with classic using '{strategy.name}' strategy")
        assert isinstance(classic_only, Pkg)
    else:
        assert 'classic' not in separate.version
        assert isinstance(retail_only, Pkg)
        assert (isinstance(classic_only, E.PkgFileUnavailable)
                and classic_only.message == f"no files compatible with retail using '{strategy.name}' strategy")

    versions = {*request.config.cache.get('flavour_explosion', ()), flavour_explosion.version}
    assert len(versions) == 1
    request.config.cache.set('flavour_explosion', tuple(versions))


@pytest.mark.asyncio
async def test_curse_latest(manager):
    latest, = (await manager.resolve([Defn('curse', 'tomcats', Strategies.latest)])).values()
    assert isinstance(latest, Pkg)


@pytest.mark.asyncio
async def test_curse_deps(manager):
    if manager.config.is_retail:
        with_deps = (await manager.resolve([Defn('curse', 'mechagon-rare-share', Strategies.default)],
                                           with_deps=True)).values()
        assert ['mechagon-rare-share', 'rare-share'] == [d.slug for d in with_deps]


@pytest.mark.asyncio
async def test_tukui(manager):
    either, retail_id, retail_slug, invalid = (await manager.resolve(
        [Defn('tukui', '1'),
         Defn('tukui', '-1'),
         Defn('tukui', 'tukui'),
         Defn('tukui', '1', Strategies.latest)])).values()
    assert isinstance(either, Pkg)
    if manager.config.is_classic:
        assert either.name == 'Tukui'
        assert isinstance(retail_id, E.PkgNonexistent)
        assert isinstance(retail_slug, E.PkgNonexistent)
    else:
        assert either.name == 'MerathilisUI'
        assert isinstance(retail_id, Pkg) and retail_id.name == 'Tukui'
        assert isinstance(retail_slug, Pkg) and retail_slug.name == 'Tukui'
    assert (isinstance(invalid, E.PkgStrategyUnsupported)
            and invalid.message == "'latest' strategy is not valid for source")


@pytest.mark.asyncio
async def test_wowi(manager):
    either, retail, classic, invalid = (await manager.resolve(
        [Defn('wowi', '21654-dejamark'),
         Defn('wowi', '21656'),    # -dejachat
         Defn('wowi', '25180-dejachatclassic'),
         Defn('wowi', '21654', Strategies.latest)])).values()
    assert isinstance(either, Pkg)
    assert isinstance(retail, Pkg)
    assert isinstance(classic, Pkg)
    assert (isinstance(invalid, E.PkgStrategyUnsupported)
            and invalid.message == "'latest' strategy is not valid for source")
