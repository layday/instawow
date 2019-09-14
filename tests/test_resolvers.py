
import pytest

from instawow.config import Config
import instawow.exceptions as E
from instawow.models import Pkg


@pytest.mark.asyncio
async def test_curse(manager):
    either, retail, classic = (await manager.resolve([('curse', 'tomcats'),
                                                      ('curse', 'method-dungeon-tools'),
                                                      ('curse', 'classiccastbars')],
                                                     strategy='default')).values()
    assert isinstance(either, Pkg)
    if manager.config.is_classic:
        assert 'classic' in either.version
        assert (isinstance(retail, E.PkgFileUnavailable)
                and retail.message == 'no files meet criteria')
        assert isinstance(classic, Pkg)
    else:
        assert 'classic' not in either.version
        assert isinstance(retail, Pkg)
        assert (isinstance(classic, E.PkgFileUnavailable)
                and classic.message == 'no files meet criteria')

    latest, = (await manager.resolve([('curse', 'tomcats')], strategy='latest')).values()
    assert isinstance(latest, Pkg)


@pytest.mark.asyncio
async def test_tukui(manager):
    either, retail = (await manager.resolve([('tukui', '1'),
                                             ('tukui', 'tukui')],
                                            strategy='default')).values()
    assert isinstance(either, Pkg)
    if manager.config.is_classic:
        assert either.name == 'Tukui'
        assert isinstance(retail, E.PkgNonexistent)
    else:
        assert either.name == 'MerathilisUI'
        assert isinstance(retail, Pkg) and retail.name == 'Tukui'

    latest, = (await manager.resolve([('tukui', '1')], strategy='latest')).values()
    assert (isinstance(latest, E.PkgStrategyUnsupported)
            and latest.message == "strategy 'latest' is not valid for source")


@pytest.mark.asyncio
async def test_wowi(manager):
    either, retail, classic = (await manager.resolve([('wowi', '21654-dejamark'),
                                                      ('wowi', '21656'),    # -dejachat
                                                      ('wowi', '25180-dejachatclassic')],
                                                     strategy='default')).values()
    assert isinstance(either, Pkg)
    if manager.config.is_classic:
        assert (isinstance(retail, E.PkgFileUnavailable)
                and retail.message == 'file is not compatible with classic')
        assert isinstance(classic, Pkg)
    else:
        assert isinstance(retail, Pkg)
        assert (isinstance(classic, E.PkgFileUnavailable)
                and classic.message == 'file is only compatible with classic')

    latest, = (await manager.resolve([('wowi', '21654')], strategy='latest')).values()
    assert (isinstance(latest, E.PkgStrategyUnsupported)
            and latest.message == "strategy 'latest' is not valid for source")
