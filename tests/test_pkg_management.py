from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import ClientError
from aresponses import ResponsesMockServer
from attrs import evolve

from instawow import results as R
from instawow.common import Defn, Strategy
from instawow.pkg_management import PkgManager
from instawow.pkg_models import Pkg


def test_auth_bound_resolvers_are_not_unloaded_if_tokens_set(
    iw_manager: PkgManager,
):
    assert {
        r.metadata.id for r in iw_manager.ctx.RESOLVERS if r.requires_access_token is not None
    }.issubset(iw_manager.ctx.resolvers)


@pytest.mark.parametrize(
    'iw_global_config_values',
    [None],
    indirect=True,
)
def test_auth_bound_resolvers_are_unloaded_if_tokens_unset(
    iw_manager: PkgManager,
):
    assert {
        r.metadata.id for r in iw_manager.ctx.RESOLVERS if r.requires_access_token is not None
    }.isdisjoint(iw_manager.ctx.resolvers)


async def test_pinning_supported_pkg(
    iw_manager: PkgManager,
):
    defn = Defn('curse', 'molinari')

    install_result = (await iw_manager.install([defn], False))[defn]
    assert type(install_result) is R.PkgInstalled

    for new_defn in (defn.with_version(install_result.pkg.version), defn):
        pin_result = (await iw_manager.pin([new_defn]))[new_defn]
        assert type(pin_result) is R.PkgInstalled
        assert pin_result.pkg.options.version_eq is bool(new_defn.strategies.version_eq)
        assert install_result.pkg.version == pin_result.pkg.version


async def test_pinning_unsupported_pkg(
    iw_manager: PkgManager,
):
    molinari_defn = Defn('wowi', '13188')

    await iw_manager.install([molinari_defn], False)
    installed_pkg = iw_manager.get_pkg(molinari_defn)
    assert installed_pkg is not None
    assert installed_pkg.options.version_eq is False

    result = (await iw_manager.pin([molinari_defn]))[molinari_defn]
    assert type(result) is R.PkgStrategiesUnsupported
    assert result.strategies == {Strategy.VersionEq}
    assert installed_pkg.options.version_eq is False


async def test_pinning_nonexistent_pkg(
    iw_manager: PkgManager,
):
    molinari_defn = Defn('curse', 'molinari')
    result = await iw_manager.pin([molinari_defn])
    assert type(result[molinari_defn]) is R.PkgNotInstalled


async def test_pinning_unsupported_nonexistent_pkg(
    iw_manager: PkgManager,
):
    molinari_defn = Defn('wowi', '13188')
    result = await iw_manager.pin([molinari_defn])
    assert type(result[molinari_defn]) is R.PkgStrategiesUnsupported


@pytest.mark.parametrize('exception', [ValueError('foo'), ClientError('bar')])
async def test_resolve_rewraps_exception_appropriately_from_resolve(
    monkeypatch: pytest.MonkeyPatch,
    iw_manager: PkgManager,
    exception: Exception,
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
    monkeypatch: pytest.MonkeyPatch,
    iw_manager: PkgManager,
    exception: Exception,
):
    async def resolve(self, defns):
        raise exception

    monkeypatch.setattr('instawow._sources.cfcore.CfCoreResolver.resolve', resolve)

    defn = Defn('curse', 'molinari')
    result = (await iw_manager.resolve([defn]))[defn]
    assert type(result) is R.InternalError
    assert result.message == f'internal error: "{exception}"'


async def test_resolve_invalid_source(
    iw_manager: PkgManager,
):
    defn = Defn('bar', 'baz')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is R.PkgSourceInvalid


async def test_resolve_plugin_hook_source(
    iw_manager: PkgManager,
):
    pytest.importorskip('instawow_test_plugin')
    defn = Defn('me', 'bar')
    results = await iw_manager.resolve([defn])
    assert type(results[defn]) is Pkg


async def test_install_can_replace_unreconciled_folders(
    iw_manager: PkgManager,
):
    molinari = iw_manager.ctx.config.addon_dir / 'Molinari'
    molinari.mkdir()

    defn = Defn('curse', 'molinari')

    result = await iw_manager.install([defn], replace_folders=False)
    assert type(result[defn]) is R.PkgConflictsWithUnreconciled
    assert not any(molinari.iterdir())

    result = await iw_manager.install([defn], replace_folders=True)
    assert type(result[defn]) is R.PkgInstalled
    assert any(molinari.iterdir())


async def test_install_cannot_replace_reconciled_folders(
    iw_manager: PkgManager,
):
    curse_defn = Defn('curse', 'molinari')
    wowi_defn = Defn('wowi', '13188-molinari')

    result = await iw_manager.install([curse_defn], replace_folders=False)
    assert type(result[curse_defn]) is R.PkgInstalled

    result = await iw_manager.install([wowi_defn], replace_folders=False)
    assert type(result[wowi_defn]) is R.PkgConflictsWithInstalled

    result = await iw_manager.install([wowi_defn], replace_folders=True)
    assert type(result[wowi_defn]) is R.PkgConflictsWithInstalled


async def test_install_recognises_renamed_pkg_from_id(
    monkeypatch: pytest.MonkeyPatch,
    iw_aresponses: ResponsesMockServer,
    iw_manager: PkgManager,
):
    iw_aresponses.add(
        'api.github.com',
        '/repos/p3lim-wow/molinarifico',
        'get',
        iw_aresponses.Response(status=404),
    )

    old_defn = Defn('github', 'p3lim-wow/molinari')
    new_defn = Defn('github', 'p3lim-wow/molinarifico')

    result = await iw_manager.install([old_defn], replace_folders=False)
    assert type(result[old_defn]) is R.PkgInstalled

    result = await iw_manager.install([old_defn], replace_folders=False)
    assert type(result[old_defn]) is R.PkgAlreadyInstalled

    result = await iw_manager.install([new_defn], replace_folders=False)
    assert type(result[new_defn]) is R.PkgNonexistent

    async def resolve(defns, with_deps=False):
        result = await orig_resolve([old_defn])
        pkg = evolve(result[old_defn], slug=new_defn.alias)
        return {new_defn: pkg}

    orig_resolve = iw_manager.resolve
    monkeypatch.setattr(iw_manager, 'resolve', resolve)

    result = await iw_manager.install([new_defn], replace_folders=False)
    assert type(result[new_defn]) is R.PkgAlreadyInstalled


async def test_update_lifecycle_while_varying_retain_defn_strategy(
    iw_manager: PkgManager,
):
    defn = Defn('curse', 'molinari')
    versioned_defn = defn.with_version('100005.97-Release')

    result = (await iw_manager.install([defn], replace_folders=False))[defn]
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


async def test_update_reinstalls_corrupted_pkgs(
    iw_manager: PkgManager,
):
    defn = Defn('curse', 'molinari')

    result = (await iw_manager.install([defn], replace_folders=False))[defn]
    assert type(result) is R.PkgInstalled

    folders = [iw_manager.ctx.config.addon_dir / f.name for f in result.pkg.folders]

    first_folder = folders[0]
    first_folder.rename(first_folder.with_name('foo'))
    assert not all(f.is_dir() for f in folders)

    result = await iw_manager.update([defn], retain_defn_strategy=False)
    assert type(result[defn]) is R.PkgUpdated
    assert all(f.is_dir() for f in folders)


@pytest.mark.parametrize('keep_folders', [True, False])
async def test_deleting_and_retaining_folders_on_remove(
    iw_manager: PkgManager, keep_folders: bool
):
    defn = Defn('curse', 'molinari')

    await iw_manager.install([defn], False)
    pkg = iw_manager.get_pkg(defn)
    assert pkg

    folders = [iw_manager.ctx.config.addon_dir / f.name for f in pkg.folders]
    assert all(f.is_dir() for f in folders)

    result = await iw_manager.remove([defn], keep_folders=keep_folders)
    assert type(result[defn]) is R.PkgRemoved
    assert not iw_manager.get_pkg(defn)
    if keep_folders:
        assert all(f.is_dir() for f in folders)
    else:
        assert not any(f.is_dir() for f in folders)


@pytest.mark.parametrize('keep_folders', [True, False])
async def test_removing_pkg_with_missing_folders(
    iw_manager: PkgManager,
    keep_folders: bool,
):
    defn = Defn('curse', 'molinari')

    result = await iw_manager.install([defn], False)

    folders = [iw_manager.ctx.config.addon_dir / f.name for f in result[defn].pkg.folders]
    for folder in folders:
        folder.rename(folder.with_name(f'Not_{folder.name}'))
    assert not any(f.is_dir() for f in folders)

    result = await iw_manager.remove([defn], keep_folders=keep_folders)
    assert type(result[defn]) is R.PkgRemoved
    assert not iw_manager.get_pkg(defn)


async def test_get_changelog_from_empty_data_url(
    iw_manager: PkgManager,
):
    assert (await iw_manager.get_changelog('github', 'data:,')) == ''


async def test_get_changelog_from_url_encoded_data_url(
    iw_manager: PkgManager,
):
    assert (await iw_manager.get_changelog('github', 'data:,foo%20bar')) == 'foo bar'


async def test_get_malformed_changelog(
    iw_manager: PkgManager,
):
    with pytest.raises(ValueError, match='Unsupported URI with scheme'):
        await iw_manager.get_changelog('github', '')


async def test_get_changelog_from_file_uri(
    iw_manager: PkgManager,
    tmp_path: Path,
):
    changelog = tmp_path / 'changelog.txt'
    changelog.write_text('test')
    assert (await iw_manager.get_changelog('github', changelog.as_uri())) == 'test'


async def test_get_changelog_from_web_url(
    iw_manager: PkgManager,
):
    assert (
        await iw_manager.get_changelog(
            'curse', 'https://api.curseforge.com/v1/mods/20338/files/3657564/changelog'
        )
    ).startswith('<h3>Changes in')
