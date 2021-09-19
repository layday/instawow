from pathlib import Path

from aiohttp import ClientError
import pytest

from instawow import results as R
from instawow.common import Strategy
from instawow.config import Flavour
from instawow.models import Pkg
from instawow.resolvers import Defn


@pytest.mark.asyncio
async def test_pinning_supported_pkg(iw_manager):
    defn = Defn('curse', 'molinari')
    install_result = await iw_manager.install([defn], False)
    pkg = install_result[defn].pkg
    version = pkg.version

    for new_defn in (defn.with_version(pkg.version), defn):
        pin_result = await iw_manager.pin([new_defn])
        pinned_pkg = pin_result[new_defn].pkg
        assert pkg.options.strategy is Strategy.default
        assert pinned_pkg.options.strategy is new_defn.strategy
        assert version == pinned_pkg.version


@pytest.mark.asyncio
async def test_pinning_unsupported_pkg(iw_manager):
    molinari_defn = Defn('wowi', '13188')
    await iw_manager.install([molinari_defn], False)
    installed_pkg = iw_manager.get_pkg(molinari_defn)
    assert installed_pkg.options.strategy == Strategy.default
    result = await iw_manager.pin([molinari_defn])
    assert (
        type(result[molinari_defn]) is R.PkgStrategyUnsupported
        and result[molinari_defn].strategy is Strategy.version
    )
    assert installed_pkg.options.strategy == Strategy.default


@pytest.mark.asyncio
async def test_pinning_nonexistent_pkg(iw_manager):
    molinari_defn = Defn('wowi', '13188')
    result = await iw_manager.pin([molinari_defn])
    assert type(result[molinari_defn]) is R.PkgNotInstalled


@pytest.mark.parametrize('exception', [ValueError('foo'), ClientError('bar')])
@pytest.mark.asyncio
async def test_resolve_rewraps_exception_appropriately_from_resolve(
    monkeypatch, iw_manager, exception
):
    async def resolve_one(self, defn, metadata):
        raise exception

    monkeypatch.setattr('instawow.resolvers.CurseResolver.resolve_one', resolve_one)

    defn = Defn('curse', 'molinari')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is R.InternalError
    assert results[defn].message == f'internal error: "{exception}"'


@pytest.mark.parametrize('exception', [ValueError('foo'), ClientError('bar')])
@pytest.mark.asyncio
async def test_resolve_rewraps_exception_appropriately_from_batch_resolve(
    monkeypatch, iw_manager, exception
):
    async def resolve(self, defns):
        raise exception

    monkeypatch.setattr('instawow.resolvers.CurseResolver.resolve', resolve)

    defn = Defn('curse', 'molinari')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is R.InternalError
    assert results[defn].message == f'internal error: "{exception}"'


@pytest.mark.asyncio
async def test_resolve_invalid_source(iw_manager):
    defn = Defn('bar', 'baz')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is R.PkgSourceInvalid


@pytest.mark.asyncio
async def test_resolve_plugin_hook_source(iw_manager):
    pytest.importorskip('instawow_test_plugin')
    defn = Defn('me', 'bar')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is Pkg


@pytest.mark.asyncio
async def test_install_can_replace_unreconciled_folders(iw_manager):
    molinari = iw_manager.config.addon_dir / 'Molinari'
    molinari.mkdir()

    defn = Defn('curse', 'molinari')

    result = await iw_manager.install([defn], replace=False)
    assert type(result[defn]) is R.PkgConflictsWithUnreconciled
    assert not any(molinari.iterdir())

    result = await iw_manager.install([defn], replace=True)
    assert type(result[defn]) is R.PkgInstalled
    assert any(molinari.iterdir())


@pytest.mark.asyncio
async def test_install_cannot_replace_reconciled_folders(iw_manager):
    curse_defn = Defn('curse', 'molinari')
    wowi_defn = Defn('wowi', '13188-molinari')

    result = await iw_manager.install([curse_defn], replace=False)
    assert type(result[curse_defn]) is R.PkgInstalled

    result = await iw_manager.install([wowi_defn], replace=False)
    assert type(result[wowi_defn]) is R.PkgConflictsWithInstalled

    result = await iw_manager.install([wowi_defn], replace=True)
    assert type(result[wowi_defn]) is R.PkgConflictsWithInstalled


@pytest.mark.asyncio
async def test_update_lifecycle_while_varying_retain_defn_strategy(iw_manager):
    defn = Defn('curse', 'molinari')
    versioned_defn = defn.with_version('80000.57-Release')

    result = await iw_manager.install([defn], replace=False)
    assert type(result[defn]) is R.PkgInstalled
    assert result[defn].pkg.options.strategy == Strategy.default

    result = await iw_manager.update([defn], retain_defn_strategy=False)
    assert type(result[defn]) is R.PkgUpToDate
    assert result[defn].is_pinned is False

    result = await iw_manager.update([versioned_defn], retain_defn_strategy=False)
    assert type(result[versioned_defn]) is R.PkgUpToDate
    assert result[versioned_defn].is_pinned is False

    result = await iw_manager.update([versioned_defn], retain_defn_strategy=True)
    assert type(result[versioned_defn]) is R.PkgUpdated
    assert result[versioned_defn].new_pkg.options.strategy == Strategy.version

    result = await iw_manager.update([defn], retain_defn_strategy=False)
    assert type(result[defn]) is R.PkgUpToDate
    assert result[defn].is_pinned is True

    result = await iw_manager.update([defn], retain_defn_strategy=True)
    assert type(result[defn]) is R.PkgUpdated
    assert result[defn].new_pkg.options.strategy == Strategy.default


@pytest.mark.parametrize('keep_folders', [True, False])
@pytest.mark.asyncio
async def test_deleting_and_retaining_folders_on_remove(iw_manager, keep_folders):
    defn = Defn('curse', 'molinari')

    await iw_manager.install([defn], False)
    folders = [iw_manager.config.addon_dir / f.name for f in iw_manager.get_pkg(defn).folders]
    assert all(f.is_dir() for f in folders)

    result = await iw_manager.remove([defn], keep_folders=keep_folders)
    assert type(result[defn]) is R.PkgRemoved
    assert not iw_manager.get_pkg(defn)
    if keep_folders:
        assert all(f.is_dir() for f in folders)
    else:
        assert not any(f.is_dir() for f in folders)


@pytest.mark.parametrize('keep_folders', [True, False])
@pytest.mark.asyncio
async def test_removing_pkg_with_missing_folders(iw_manager, keep_folders):
    defn = Defn('curse', 'molinari')

    result = await iw_manager.install([defn], False)
    folders = [iw_manager.config.addon_dir / f.name for f in result[defn].pkg.folders]
    for folder in folders:
        folder.rename(folder.with_name(f'Not_{folder.name}'))
    assert not any(f.is_dir() for f in folders)

    result = await iw_manager.remove([defn], keep_folders=keep_folders)
    assert type(result[defn]) is R.PkgRemoved
    assert not iw_manager.get_pkg(defn)


@pytest.mark.asyncio
async def test_basic_search(iw_manager):
    results = await iw_manager.search('molinari', limit=5)
    defns = {Defn(e.source, e.slug or e.id) for e in results}
    assert {Defn('curse', 'molinari'), Defn('wowi', '13188')} <= defns


@pytest.mark.asyncio
async def test_search_source_filtering(iw_manager):
    results = await iw_manager.search('molinari', limit=5, sources={'curse'})
    defns = {Defn(e.source, e.slug or e.id) for e in results}
    assert all(d.source == 'curse' for d in defns)
    assert {Defn('curse', 'molinari')} <= defns


@pytest.mark.asyncio
async def test_search_caters_to_flavour(iw_manager):
    results = await iw_manager.search('AtlasLootClassic', limit=5)
    defns = {Defn(e.source, e.slug or e.id) for e in results}
    if iw_manager.config.game_flavour is Flavour.vanilla_classic:
        assert Defn('curse', 'atlaslootclassic') in defns
    else:
        assert Defn('curse', 'atlaslootclassic') not in defns


@pytest.mark.asyncio
async def test_get_changelog_from_empty_data_url(iw_manager):
    assert (await iw_manager.get_changelog('data:,')) == ''


@pytest.mark.asyncio
async def test_get_changelog_from_url_encoded_data_url(iw_manager):
    assert (await iw_manager.get_changelog('data:,foo%20bar')) == 'foo bar'


@pytest.mark.asyncio
async def test_get_malformed_changelog(iw_manager):
    with pytest.raises(ValueError, match='Unsupported URL with scheme'):
        await iw_manager.get_changelog('')


@pytest.mark.asyncio
async def test_get_changelog_from_file_uri(iw_manager):
    assert (
        await iw_manager.get_changelog(
            (Path(__file__).parent / 'fixtures' / 'curse-addon-changelog.txt').as_uri()
        )
    ).startswith('<h3>Changes in 90000.73-Release:</h3>')


@pytest.mark.asyncio
async def test_get_changelog_from_web_url(iw_manager):
    assert (
        await iw_manager.get_changelog(
            'https://addons-ecs.forgesvc.net/api/v2/addon/20338/file/3152268/changelog'
        )
    ).startswith('<h3>Changes in 90000.73-Release:</h3>')
