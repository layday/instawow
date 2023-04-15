from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from aiohttp import ClientError

from instawow import results as R
from instawow.common import Defn, Flavour, Strategy
from instawow.manager import Manager
from instawow.models import Pkg


def test_auth_bound_resolvers_are_not_unloaded_if_tokens_set(iw_manager: Manager):
    assert {
        r.metadata.id for r in iw_manager.RESOLVERS if r.requires_access_token is not None
    }.issubset(iw_manager.resolvers)


@pytest.mark.parametrize(
    'iw_global_config_values',
    [None],
    indirect=True,
)
def test_auth_bound_resolvers_are_unloaded_if_tokens_unset(iw_manager: Manager):
    assert {
        r.metadata.id for r in iw_manager.RESOLVERS if r.requires_access_token is not None
    }.isdisjoint(iw_manager.resolvers)


async def test_pinning_supported_pkg(iw_manager: Manager):
    defn = Defn('curse', 'molinari')

    install_result = (await iw_manager.install([defn], False))[defn]
    assert type(install_result) is R.PkgInstalled

    for new_defn in (defn.with_version(install_result.pkg.version), defn):
        pin_result = (await iw_manager.pin([new_defn]))[new_defn]
        assert type(pin_result) is R.PkgInstalled
        assert pin_result.pkg.options.version_eq is bool(new_defn.strategies.version_eq)
        assert install_result.pkg.version == pin_result.pkg.version


async def test_pinning_unsupported_pkg(iw_manager: Manager):
    molinari_defn = Defn('wowi', '13188')

    await iw_manager.install([molinari_defn], False)
    installed_pkg = iw_manager.get_pkg(molinari_defn)
    assert installed_pkg is not None
    assert installed_pkg.options.version_eq is False

    result = (await iw_manager.pin([molinari_defn]))[molinari_defn]
    assert type(result) is R.PkgStrategiesUnsupported
    assert result.strategies == {Strategy.version_eq}
    assert installed_pkg.options.version_eq is False


async def test_pinning_nonexistent_pkg(iw_manager: Manager):
    molinari_defn = Defn('curse', 'molinari')
    result = await iw_manager.pin([molinari_defn])
    assert type(result[molinari_defn]) is R.PkgNotInstalled


async def test_pinning_unsupported_nonexistent_pkg(iw_manager: Manager):
    molinari_defn = Defn('wowi', '13188')
    result = await iw_manager.pin([molinari_defn])
    assert type(result[molinari_defn]) is R.PkgStrategiesUnsupported


@pytest.mark.parametrize('exception', [ValueError('foo'), ClientError('bar')])
async def test_resolve_rewraps_exception_appropriately_from_resolve(
    monkeypatch: pytest.MonkeyPatch, iw_manager: Manager, exception: Exception
):
    async def resolve_one(self, defn, metadata):
        raise exception

    monkeypatch.setattr('instawow._sources.cfcore.CfCoreResolver.resolve_one', resolve_one)

    defn = Defn('curse', 'molinari')
    result = (await iw_manager.resolve([defn]))[defn]
    assert type(result) is R.InternalError
    assert result.message == f'internal error: "{exception}"'


@pytest.mark.parametrize('exception', [ValueError('foo'), ClientError('bar')])
async def test_resolve_rewraps_exception_appropriately_from_batch_resolve(
    monkeypatch: pytest.MonkeyPatch, iw_manager: Manager, exception: Exception
):
    async def resolve(self, defns):
        raise exception

    monkeypatch.setattr('instawow._sources.cfcore.CfCoreResolver.resolve', resolve)

    defn = Defn('curse', 'molinari')
    result = (await iw_manager.resolve([defn]))[defn]
    assert type(result) is R.InternalError
    assert result.message == f'internal error: "{exception}"'


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

    result = (await iw_manager.install([defn], replace=False))[defn]
    assert type(result) is R.PkgInstalled

    result = (await iw_manager.update([defn], retain_defn_strategy=False))[defn]
    assert type(result) is R.PkgUpToDate
    assert result.is_pinned is False

    result = (await iw_manager.update([versioned_defn], retain_defn_strategy=False))[
        versioned_defn
    ]
    assert type(result) is R.PkgUpToDate
    assert result.is_pinned is False

    result = (await iw_manager.update([versioned_defn], retain_defn_strategy=True))[versioned_defn]
    assert type(result) is R.PkgUpdated
    assert result.new_pkg.options.version_eq is True

    result = (await iw_manager.update([defn], retain_defn_strategy=False))[defn]
    assert type(result) is R.PkgUpToDate
    assert result.is_pinned is True

    result = (await iw_manager.update([defn], retain_defn_strategy=True))[defn]
    assert type(result) is R.PkgUpdated
    assert result.new_pkg.options.version_eq is False


async def test_update_reinstalls_corrupted_pkgs(iw_manager: Manager):
    defn = Defn('curse', 'molinari')

    result = (await iw_manager.install([defn], replace=False))[defn]
    assert type(result) is R.PkgInstalled

    folders = [iw_manager.config.addon_dir / f.name for f in result.pkg.folders]

    first_folder = folders[0]
    first_folder.rename(first_folder.with_name('foo'))
    assert not all(f.is_dir() for f in folders)

    result = await iw_manager.update([defn], retain_defn_strategy=False)
    assert type(result[defn]) is R.PkgUpdated
    assert all(f.is_dir() for f in folders)


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


@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
async def test_search_flavour_filtering(iw_manager: Manager):
    results = await iw_manager.search('AtlasLootClassic', limit=5)
    faux_defns = {(e.source, e.slug or e.id) for e in results}
    if iw_manager.config.game_flavour in {
        Flavour.vanilla_classic,
        Flavour.classic,
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
    assert (await iw_manager.get_changelog('github', 'data:,')) == ''


async def test_get_changelog_from_url_encoded_data_url(iw_manager: Manager):
    assert (await iw_manager.get_changelog('github', 'data:,foo%20bar')) == 'foo bar'


async def test_get_malformed_changelog(iw_manager: Manager):
    with pytest.raises(ValueError, match='Unsupported URI with scheme'):
        await iw_manager.get_changelog('github', '')


async def test_get_changelog_from_file_uri(iw_manager: Manager, tmp_path: Path):
    changelog = tmp_path / 'changelog.txt'
    changelog.write_text('test')
    assert (await iw_manager.get_changelog('github', changelog.as_uri())) == 'test'


async def test_get_changelog_from_web_url(iw_manager: Manager):
    assert (
        await iw_manager.get_changelog(
            'curse', 'https://api.curseforge.com/v1/mods/20338/files/3657564/changelog'
        )
    ).startswith('<h3>Changes in 90200.82-Release:</h3>')
