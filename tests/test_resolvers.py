import pytest

import instawow.exceptions as E
from instawow.models import Pkg
from instawow.resolvers import Defn, Strategies


@pytest.mark.asyncio
async def test_curse(manager, request):
    either, retail, classic = (await manager.resolve([Defn('curse', 'tomcats'),
                                                      Defn('curse', 'method-dungeon-tools'),
                                                      Defn('curse', 'classiccastbars')],
                                                     strategy=Strategies.default)).values()
    assert isinstance(either, Pkg)
    if manager.config.is_classic:
        assert 'classic' in either.version
        assert (isinstance(retail, E.PkgFileUnavailable)
                and retail.message == "no files compatible with classic using 'default' strategy")
        assert isinstance(classic, Pkg)
    else:
        assert 'classic' not in either.version
        assert isinstance(retail, Pkg)
        assert (isinstance(classic, E.PkgFileUnavailable)
                and classic.message == "no files compatible with retail using 'default' strategy")

    flavour_explosion, = (await manager.resolve([Defn('curse', 'elkbuffbars')],
                                                strategy=Strategies.default)).values()
    versions = {*request.config.cache.get('flavour_explosion', ()),
                flavour_explosion.version}
    assert len(versions) == 1
    request.config.cache.set('flavour_explosion', tuple(versions))

    latest, = (await manager.resolve([Defn('curse', 'tomcats')], strategy=Strategies.latest)).values()
    assert isinstance(latest, Pkg)


@pytest.mark.asyncio
async def test_tukui(manager):
    either, retail = (await manager.resolve([Defn('tukui', '1'),
                                             Defn('tukui', 'tukui')],
                                            strategy=Strategies.default)).values()
    assert isinstance(either, Pkg)
    if manager.config.is_classic:
        assert either.name == 'Tukui'
        assert isinstance(retail, E.PkgNonexistent)
    else:
        assert either.name == 'MerathilisUI'
        assert isinstance(retail, Pkg) and retail.name == 'Tukui'

    latest, = (await manager.resolve([Defn('tukui', '1')], strategy=Strategies.latest)).values()
    assert (isinstance(latest, E.PkgStrategyUnsupported)
            and latest.message == "'latest' strategy is not valid for source")


@pytest.mark.asyncio
async def test_wowi(manager):
    either, retail, classic = (await manager.resolve([Defn('wowi', '21654-dejamark'),
                                                      Defn('wowi', '21656'),    # -dejachat
                                                      Defn('wowi', '25180-dejachatclassic')],
                                                     strategy=Strategies.default)).values()
    assert isinstance(either, Pkg)
    if manager.config.is_classic:
        assert (isinstance(retail, E.PkgFileUnavailable)
                and retail.message == 'file is not compatible with classic')
        assert isinstance(classic, Pkg)
    else:
        assert isinstance(retail, Pkg)
        assert (isinstance(classic, E.PkgFileUnavailable)
                and classic.message == 'file is only compatible with classic')

    latest, = (await manager.resolve([Defn('wowi', '21654')], strategy=Strategies.latest)).values()
    assert (isinstance(latest, E.PkgStrategyUnsupported)
            and latest.message == "'latest' strategy is not valid for source")
