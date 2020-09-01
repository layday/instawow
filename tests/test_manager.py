import pytest

from instawow import exceptions as E
from instawow.resolvers import Defn, Strategies


@pytest.mark.asyncio
async def test_finding_damaged_pkgs(mock_all, manager):
    molinari_defn = Defn.get('curse', 'molinari')
    install_result = await manager.install([molinari_defn], False)
    installed_pkg = install_result[molinari_defn].pkg
    assert not manager.find_damaged_pkgs()
    (manager.config.addon_dir / installed_pkg.folders[0].name).rename(
        manager.config.addon_dir / 'Foo'
    )
    damaged_pkgs = manager.find_damaged_pkgs()
    assert installed_pkg in damaged_pkgs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'defn',
    [
        Defn.get('curse', 'molinari'),
        Defn.get('curse', 'molinari').with_version('70300.51-Release'),
    ],
)
async def test_pinning_supported(mock_all, manager, defn):
    install_result = await manager.install([defn], False)
    installed_pkg = install_result[defn].pkg
    version = installed_pkg.version
    assert installed_pkg.options.strategy == defn.strategy.value
    pin_result = await manager.pin([defn])
    assert installed_pkg.options.strategy == pin_result[defn].pkg.options.strategy == 'version'
    assert version == pin_result[defn].pkg.version
    pin_result = await manager.pin([defn], True)
    assert installed_pkg.options.strategy == pin_result[defn].pkg.options.strategy == 'default'


@pytest.mark.asyncio
async def test_pinning_unsupported(mock_all, manager):
    molinari_defn = Defn.get('wowi', '13188')
    await manager.install([molinari_defn], False)
    installed_pkg = manager.get_pkg(molinari_defn)
    assert installed_pkg.options.strategy == 'default'
    result = await manager.pin([molinari_defn])
    assert (
        isinstance(result[molinari_defn], E.PkgStrategyUnsupported)
        and result[molinari_defn].strategy == Strategies.version
    )
    assert installed_pkg.options.strategy == 'default'


@pytest.mark.asyncio
async def test_pinning_nonexistent(mock_all, manager):
    molinari_defn = Defn.get('wowi', '13188')
    result = await manager.pin([molinari_defn])
    assert isinstance(result[molinari_defn], E.PkgNotInstalled)
