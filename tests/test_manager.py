import pytest

from instawow import exceptions as E
from instawow.resolvers import Defn, Strategy


@pytest.fixture(autouse=True)
def mock(mock_all):
    pass


@pytest.mark.asyncio
async def test_pinning_supported_pkg(manager):
    defn = Defn('curse', 'molinari')
    install_result = await manager.install([defn], False)
    pkg = install_result[defn].pkg
    version = pkg.version

    for new_defn in (defn.with_version(pkg.version), defn):
        pin_result = await manager.pin([new_defn])
        pinned_pkg = pin_result[new_defn].pkg
        assert pkg.options.strategy == pinned_pkg.options.strategy == new_defn.strategy.name
        assert version == pinned_pkg.version


@pytest.mark.asyncio
async def test_pinning_unsupported_pkg(manager):
    molinari_defn = Defn('wowi', '13188')
    await manager.install([molinari_defn], False)
    installed_pkg = manager.get_pkg(molinari_defn)
    assert installed_pkg.options.strategy == 'default'
    result = await manager.pin([molinari_defn])
    assert (
        isinstance(result[molinari_defn], E.PkgStrategyUnsupported)
        and result[molinari_defn].strategy == Strategy.version
    )
    assert installed_pkg.options.strategy == 'default'


@pytest.mark.asyncio
async def test_pinning_nonexistent_pkg(manager):
    molinari_defn = Defn('wowi', '13188')
    result = await manager.pin([molinari_defn])
    assert isinstance(result[molinari_defn], E.PkgNotInstalled)


@pytest.mark.asyncio
async def test_replacing_folders_on_install(manager):
    molinari = manager.config.addon_dir / 'Molinari'
    molinari.mkdir()

    defn = Defn('curse', 'molinari')

    result = await manager.install([defn], replace=False)
    assert isinstance(result[defn], E.PkgConflictsWithUnreconciled)
    assert not any(molinari.iterdir())

    result = await manager.install([defn], replace=True)
    assert isinstance(result[defn], E.PkgInstalled)
    assert any(molinari.iterdir())


@pytest.mark.parametrize('keep_folders', [True, False])
@pytest.mark.asyncio
async def test_deleting_and_retaining_folders_on_remove(manager, keep_folders):
    defn = Defn('curse', 'molinari')

    await manager.install([defn], False)
    folders = [manager.config.addon_dir / f.name for f in manager.get_pkg(defn).folders]
    assert all(f.is_dir() for f in folders)

    await manager.remove([defn], keep_folders=keep_folders)
    assert not manager.get_pkg(defn)
    if keep_folders:
        assert all(f.is_dir() for f in folders)
    else:
        assert not any(f.is_dir() for f in folders)


@pytest.mark.asyncio
async def test_finding_damaged_pkgs(manager):
    molinari_defn = Defn('curse', 'molinari')
    install_result = await manager.install([molinari_defn], False)
    installed_pkg = install_result[molinari_defn].pkg
    assert not manager.find_damaged_pkgs()
    (manager.config.addon_dir / installed_pkg.folders[0].name).rename(
        manager.config.addon_dir / 'Foo'
    )
    damaged_pkgs = manager.find_damaged_pkgs()
    assert installed_pkg in damaged_pkgs
