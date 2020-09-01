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
async def test_pinning_supported(mock_all, manager):
    defn = Defn.get('curse', 'molinari')
    install_result = await manager.install([defn], False)
    pkg = install_result[defn].pkg
    version = pkg.version

    for new_defn in (defn.with_version(pkg.version), defn):
        pin_result = await manager.pin([new_defn])
        pinned_pkg = pin_result[new_defn].pkg
        assert pkg.options.strategy == pinned_pkg.options.strategy == new_defn.strategy.name
        assert version == pinned_pkg.version


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
