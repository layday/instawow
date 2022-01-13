from __future__ import annotations

import datetime
from pathlib import Path

from aiohttp import ClientError
from aresponses import ResponsesMockServer
import pytest

from instawow import results as R
from instawow.common import Flavour, Strategy
from instawow.manager import Manager, is_outdated
from instawow.models import Pkg
from instawow.resolvers import Defn


async def test_pinning_supported_pkg(iw_manager: Manager):
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


async def test_pinning_unsupported_pkg(iw_manager: Manager):
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


async def test_pinning_nonexistent_pkg(iw_manager: Manager):
    molinari_defn = Defn('wowi', '13188')
    result = await iw_manager.pin([molinari_defn])
    assert type(result[molinari_defn]) is R.PkgNotInstalled


@pytest.mark.parametrize('exception', [ValueError('foo'), ClientError('bar')])
async def test_resolve_rewraps_exception_appropriately_from_resolve(
    monkeypatch: pytest.MonkeyPatch, iw_manager: Manager, exception: Exception
):
    async def resolve_one(self, defn, metadata):
        raise exception

    monkeypatch.setattr('instawow.resolvers.CurseResolver.resolve_one', resolve_one)

    defn = Defn('curse', 'molinari')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is R.InternalError
    assert results[defn].message == f'internal error: "{exception}"'


@pytest.mark.parametrize('exception', [ValueError('foo'), ClientError('bar')])
async def test_resolve_rewraps_exception_appropriately_from_batch_resolve(
    monkeypatch: pytest.MonkeyPatch, iw_manager: Manager, exception: Exception
):
    async def resolve(self, defns):
        raise exception

    monkeypatch.setattr('instawow.resolvers.CurseResolver.resolve', resolve)

    defn = Defn('curse', 'molinari')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is R.InternalError
    assert results[defn].message == f'internal error: "{exception}"'


async def test_resolve_invalid_source(iw_manager: Manager):
    defn = Defn('bar', 'baz')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is R.PkgSourceInvalid


async def test_resolve_plugin_hook_source(iw_manager: Manager):
    pytest.importorskip('instawow_test_plugin')
    defn = Defn('me', 'bar')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is Pkg


async def test_install_can_replace_unreconciled_folders(iw_manager: Manager):
    molinari = iw_manager.config.addon_dir / 'Molinari'
    molinari.mkdir()

    defn = Defn('curse', 'molinari')

    result = await iw_manager.install([defn], replace=False)
    assert type(result[defn]) is R.PkgConflictsWithUnreconciled
    assert not any(molinari.iterdir())

    result = await iw_manager.install([defn], replace=True)
    assert type(result[defn]) is R.PkgInstalled
    assert any(molinari.iterdir())


async def test_install_cannot_replace_reconciled_folders(iw_manager: Manager):
    curse_defn = Defn('curse', 'molinari')
    wowi_defn = Defn('wowi', '13188-molinari')

    result = await iw_manager.install([curse_defn], replace=False)
    assert type(result[curse_defn]) is R.PkgInstalled

    result = await iw_manager.install([wowi_defn], replace=False)
    assert type(result[wowi_defn]) is R.PkgConflictsWithInstalled

    result = await iw_manager.install([wowi_defn], replace=True)
    assert type(result[wowi_defn]) is R.PkgConflictsWithInstalled


async def test_update_lifecycle_while_varying_retain_defn_strategy(iw_manager: Manager):
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
async def test_deleting_and_retaining_folders_on_remove(iw_manager: Manager, keep_folders: bool):
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
async def test_removing_pkg_with_missing_folders(iw_manager: Manager, keep_folders: bool):
    defn = Defn('curse', 'molinari')

    result = await iw_manager.install([defn], False)
    folders = [iw_manager.config.addon_dir / f.name for f in result[defn].pkg.folders]
    for folder in folders:
        folder.rename(folder.with_name(f'Not_{folder.name}'))
    assert not any(f.is_dir() for f in folders)

    result = await iw_manager.remove([defn], keep_folders=keep_folders)
    assert type(result[defn]) is R.PkgRemoved
    assert not iw_manager.get_pkg(defn)


async def test_basic_search(iw_manager: Manager):
    limit = 5
    results = await iw_manager.search('molinari', limit=limit)
    assert len(results) <= 5
    assert {('curse', 'molinari'), ('wowi', '13188')} <= {
        (e.source, e.slug or e.id) for e in results
    }


async def test_search_flavour_filtering(iw_manager: Manager):
    results = await iw_manager.search('AtlasLootClassic', limit=5)
    faux_defns = {(e.source, e.slug or e.id) for e in results}
    if iw_manager.config.game_flavour in {
        Flavour.vanilla_classic,
        Flavour.burning_crusade_classic,
    }:
        assert ('curse', 'atlaslootclassic') in faux_defns
    else:
        assert ('curse', 'atlaslootclassic') not in faux_defns


async def test_search_source_filtering(iw_manager: Manager):
    results = await iw_manager.search('molinari', limit=5, sources={'curse'})
    assert all(e.source == 'curse' for e in results)
    assert {('curse', 'molinari')} <= {(e.source, e.slug) for e in results}


async def test_search_date_filtering(iw_manager: Manager):
    start_date = datetime.datetime.now(tz=datetime.timezone.utc) - datetime.timedelta(days=365)
    results = await iw_manager.search('molinari', limit=5, start_date=start_date)
    assert all(e.last_updated > start_date for e in results)


async def test_search_unknown_source(iw_manager: Manager):
    with pytest.raises(ValueError, match='Unknown source'):
        await iw_manager.search('molinari', limit=5, sources={'foo'})


async def test_get_changelog_from_empty_data_url(iw_manager: Manager):
    assert (await iw_manager.get_changelog('data:,')) == ''


async def test_get_changelog_from_url_encoded_data_url(iw_manager: Manager):
    assert (await iw_manager.get_changelog('data:,foo%20bar')) == 'foo bar'


async def test_get_malformed_changelog(iw_manager: Manager):
    with pytest.raises(ValueError, match='Unsupported URI with scheme'):
        await iw_manager.get_changelog('')


async def test_get_changelog_from_file_uri(iw_manager: Manager):
    assert (
        await iw_manager.get_changelog(
            (Path(__file__).parent / 'fixtures' / 'curse-addon-changelog.txt').as_uri()
        )
    ).startswith('<h3>Changes in 90105.81-Release:</h3>')


async def test_get_changelog_from_web_url(iw_manager: Manager):
    assert (
        await iw_manager.get_changelog(
            'https://addons-ecs.forgesvc.net/api/v2/addon/20338/file/3475338/changelog'
        )
    ).startswith('<h3>Changes in 90105.81-Release:</h3>')


@pytest.mark.iw_no_mock_http
async def test_is_outdated_works_in_variety_of_scenarios(
    monkeypatch: pytest.MonkeyPatch, aresponses: ResponsesMockServer, iw_temp_dir: Path
):
    pypi_version = iw_temp_dir.joinpath('.pypi_version')
    if pypi_version.exists():
        pypi_version.unlink()

    # version == '0.0.0', version not cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.0.0')
        assert await is_outdated() == (False, '')

    # Update check disabled, version not cached
    with monkeypatch.context() as patcher:
        patcher.setenv('INSTAWOW_AUTO_UPDATE_CHECK', '0')
        assert await is_outdated() == (False, '')

    # Endpoint not responsive, version not cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.1.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            aresponses.Response(status=500),
        )
        assert await is_outdated() == (False, '0.1.0')

    # Endpoint responsive, version not cached and version different
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.1.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            {'info': {'version': '1.0.0'}},
        )
        assert await is_outdated() == (True, '1.0.0')

    # version == '0.0.0', version cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.0.0')
        assert await is_outdated() == (False, '')

    # Update check disabled, version cached
    with monkeypatch.context() as patcher:
        patcher.setenv('INSTAWOW_AUTO_UPDATE_CHECK', '0')
        assert await is_outdated() == (False, '')

    # Endpoint not responsive, version cached
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.1.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            aresponses.Response(status=500),
        )
        assert await is_outdated() == (True, '1.0.0')

    # Endpoint responsive, version cached and version same
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '0.1.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            {'info': {'version': '1.0.0'}},
        )
        assert await is_outdated() == (True, '1.0.0')

    # Endpoint responsive, version cached and version different
    with monkeypatch.context() as patcher:
        patcher.setattr('instawow.__version__', '1.0.0')
        aresponses.add(
            'pypi.org',
            '/pypi/instawow/json',
            'get',
            {'info': {'version': '1.0.0'}},
        )
        assert await is_outdated() == (False, '1.0.0')
