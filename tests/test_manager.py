from aiohttp import ClientError
import pytest

from instawow import results as E
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
        assert pkg.options.strategy == pinned_pkg.options.strategy == new_defn.strategy
        assert version == pinned_pkg.version


@pytest.mark.asyncio
async def test_pinning_unsupported_pkg(manager):
    molinari_defn = Defn('wowi', '13188')
    await manager.install([molinari_defn], False)
    installed_pkg = manager.get_pkg(molinari_defn)
    assert installed_pkg.options.strategy == Strategy.default
    result = await manager.pin([molinari_defn])
    assert (
        type(result[molinari_defn]) is E.PkgStrategyUnsupported
        and result[molinari_defn].strategy is Strategy.version
    )
    assert installed_pkg.options.strategy == Strategy.default


@pytest.mark.asyncio
async def test_pinning_nonexistent_pkg(manager):
    molinari_defn = Defn('wowi', '13188')
    result = await manager.pin([molinari_defn])
    assert type(result[molinari_defn]) is E.PkgNotInstalled


@pytest.mark.parametrize('exception', [ValueError('foo'), ClientError('bar')])
@pytest.mark.asyncio
async def test_resolve_rewraps_exception_appropriately_from_resolve(
    monkeypatch, manager, exception
):
    async def resolve_one(self, defn, metadata):
        raise exception

    monkeypatch.setattr('instawow.resolvers.CurseResolver.resolve_one', resolve_one)

    defn = Defn('curse', 'molinari')
    results = await manager.resolve([defn])
    assert type(results[defn]) is E.InternalError
    assert results[defn].message == f'internal error: "{exception}"'


@pytest.mark.parametrize('exception', [ValueError('foo'), ClientError('bar')])
@pytest.mark.asyncio
async def test_resolve_rewraps_exception_appropriately_from_batch_resolve(
    monkeypatch, manager, exception
):
    async def resolve(self, defns):
        raise exception

    monkeypatch.setattr('instawow.resolvers.CurseResolver.resolve', resolve)

    defn = Defn('curse', 'molinari')
    results = await manager.resolve([defn])
    assert type(results[defn]) is E.InternalError
    assert results[defn].message == f'internal error: "{exception}"'


@pytest.mark.asyncio
async def test_install_can_replace_unreconciled_folders(manager):
    molinari = manager.config.addon_dir / 'Molinari'
    molinari.mkdir()

    defn = Defn('curse', 'molinari')

    result = await manager.install([defn], replace=False)
    assert type(result[defn]) is E.PkgConflictsWithUnreconciled
    assert not any(molinari.iterdir())

    result = await manager.install([defn], replace=True)
    assert type(result[defn]) is E.PkgInstalled
    assert any(molinari.iterdir())


@pytest.mark.asyncio
async def test_install_cannot_replace_reconciled_folders(manager):
    curse_defn = Defn('curse', 'molinari')
    wowi_defn = Defn('wowi', '13188-molinari')

    result = await manager.install([curse_defn], replace=False)
    assert type(result[curse_defn]) is E.PkgInstalled

    result = await manager.install([wowi_defn], replace=False)
    assert type(result[wowi_defn]) is E.PkgConflictsWithInstalled

    result = await manager.install([wowi_defn], replace=True)
    assert type(result[wowi_defn]) is E.PkgConflictsWithInstalled


@pytest.mark.asyncio
async def test_update_lifecycle_while_varying_retain_strategy(manager):
    defn = Defn('curse', 'molinari')
    versioned_defn = defn.with_version('80000.57-Release')

    result = await manager.install([defn], replace=False)
    assert type(result[defn]) is E.PkgInstalled
    assert result[defn].pkg.options.strategy == Strategy.default

    result = await manager.update([defn], retain_strategy=False)
    assert type(result[defn]) is E.PkgUpToDate
    assert result[defn].is_pinned is False

    result = await manager.update([versioned_defn], retain_strategy=False)
    assert type(result[versioned_defn]) is E.PkgUpToDate
    assert result[versioned_defn].is_pinned is False

    result = await manager.update([versioned_defn], retain_strategy=True)
    assert type(result[versioned_defn]) is E.PkgUpdated
    assert result[versioned_defn].new_pkg.options.strategy == Strategy.version

    result = await manager.update([defn], retain_strategy=False)
    assert type(result[defn]) is E.PkgUpToDate
    assert result[defn].is_pinned is True

    result = await manager.update([defn], retain_strategy=True)
    assert type(result[defn]) is E.PkgUpdated
    assert result[defn].new_pkg.options.strategy == Strategy.default


@pytest.mark.parametrize('keep_folders', [True, False])
@pytest.mark.asyncio
async def test_deleting_and_retaining_folders_on_remove(manager, keep_folders):
    defn = Defn('curse', 'molinari')

    await manager.install([defn], False)
    folders = [manager.config.addon_dir / f.name for f in manager.get_pkg(defn).folders]
    assert all(f.is_dir() for f in folders)

    result = await manager.remove([defn], keep_folders=keep_folders)
    assert type(result[defn]) is E.PkgRemoved
    assert not manager.get_pkg(defn)
    if keep_folders:
        assert all(f.is_dir() for f in folders)
    else:
        assert not any(f.is_dir() for f in folders)


@pytest.mark.parametrize('keep_folders', [True, False])
@pytest.mark.asyncio
async def test_removing_pkg_with_missing_folders(manager, keep_folders):
    defn = Defn('curse', 'molinari')

    await manager.install([defn], False)
    folders = [manager.config.addon_dir / f.name for f in manager.get_pkg(defn).folders]
    for folder in folders:
        folder.rename(folder.with_name(f'Not_{folder.name}'))
    assert not any(f.is_dir() for f in folders)

    result = await manager.remove([defn], keep_folders=keep_folders)
    assert type(result[defn]) is E.PkgRemoved
    assert not manager.get_pkg(defn)
