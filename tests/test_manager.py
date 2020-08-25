import pytest

from instawow.resolvers import Defn


@pytest.mark.asyncio
async def test_finding_damaged_pkgs(mock_all, manager):
    molinari_defn = Defn(source='curse', name='molinari')
    molinari = (await manager.install([molinari_defn], False))[molinari_defn].pkg
    assert not manager.find_damaged_pkgs()
    (manager.config.addon_dir / molinari.folders[0].name).rename(manager.config.addon_dir / 'Foo')
    damaged_pkgs = manager.find_damaged_pkgs()
    assert molinari in damaged_pkgs
