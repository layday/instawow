from __future__ import annotations

from pathlib import Path

import aiohttp
import aresponses
import attrs
import pytest

from instawow import pkg_management
from instawow import results as R
from instawow.definitions import Defn, Strategy
from instawow.pkg_models import Pkg
from instawow.shared_ctx import ConfigBoundCtx

from .fixtures.http import Route


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_pinning_supported_pkg(iw_config_ctx: ConfigBoundCtx):
    defn = Defn('curse', 'molinari')

    install_result = (await pkg_management.install(iw_config_ctx, [defn], replace_folders=False))[
        defn
    ]
    assert type(install_result) is R.PkgInstalled

    for new_defn in (defn.with_version(install_result.pkg.version), defn):
        pin_result = (await pkg_management.pin(iw_config_ctx, [new_defn]))[new_defn]
        assert type(pin_result) is R.PkgInstalled
        assert pin_result.pkg.options.version_eq is bool(new_defn.strategies[Strategy.VersionEq])
        assert install_result.pkg.version == pin_result.pkg.version


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_pinning_unsupported_pkg(iw_config_ctx: ConfigBoundCtx):
    molinari_defn = Defn('wowi', '13188')

    await pkg_management.install(iw_config_ctx, [molinari_defn], replace_folders=False)
    installed_pkg = pkg_management.get_pkg(iw_config_ctx, molinari_defn)
    assert installed_pkg is not None
    assert installed_pkg.options.version_eq is False

    result = (await pkg_management.pin(iw_config_ctx, [molinari_defn]))[molinari_defn]
    assert type(result) is R.PkgStrategiesUnsupported
    assert result.strategies == {Strategy.VersionEq}
    assert installed_pkg.options.version_eq is False


async def test_pinning_nonexistent_pkg(iw_config_ctx: ConfigBoundCtx):
    molinari_defn = Defn('curse', 'molinari')
    result = await pkg_management.pin(iw_config_ctx, [molinari_defn])
    assert type(result[molinari_defn]) is R.PkgNotInstalled


async def test_pinning_unsupported_nonexistent_pkg(iw_config_ctx: ConfigBoundCtx):
    molinari_defn = Defn('wowi', '13188')
    result = await pkg_management.pin(iw_config_ctx, [molinari_defn])
    assert type(result[molinari_defn]) is R.PkgStrategiesUnsupported


@pytest.mark.parametrize('exception', [ValueError('foo'), aiohttp.ClientError('bar')])
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_resolve_rewraps_exception_appropriately_from_resolve(
    monkeypatch: pytest.MonkeyPatch,
    iw_config_ctx: ConfigBoundCtx,
    exception: Exception,
):
    async def resolve_one(self, defn, metadata):
        raise exception

    monkeypatch.setattr('instawow.resolvers.BaseResolver.resolve_one', resolve_one)

    defn = Defn('curse', 'molinari')
    result = (await pkg_management.resolve(iw_config_ctx, [defn]))[defn]
    assert type(result) is R.InternalError
    assert result.message == f'internal error: "{exception}"'


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_resolve_invalid_source(iw_config_ctx: ConfigBoundCtx):
    defn = Defn('bar', 'baz')
    results = await pkg_management.resolve(iw_config_ctx, [defn])
    assert type(results[defn]) is R.PkgSourceInvalid


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_resolve_plugin_hook_source(iw_config_ctx: ConfigBoundCtx):
    pytest.importorskip('instawow_test_plugin')
    defn = Defn('me', 'bar')
    results = await pkg_management.resolve(iw_config_ctx, [defn])
    assert type(results[defn]) is Pkg


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_install_can_replace_unreconciled_folders(
    iw_config_ctx: ConfigBoundCtx,
):
    molinari = iw_config_ctx.config.addon_dir / 'Molinari'
    molinari.mkdir()

    defn = Defn('curse', 'molinari')

    result = await pkg_management.install(iw_config_ctx, [defn], replace_folders=False)
    assert type(result[defn]) is R.PkgConflictsWithUnreconciled
    assert not any(molinari.iterdir())

    result = await pkg_management.install(iw_config_ctx, [defn], replace_folders=True)
    assert type(result[defn]) is R.PkgInstalled
    assert any(molinari.iterdir())


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_install_cannot_replace_reconciled_folders(iw_config_ctx: ConfigBoundCtx):
    curse_defn = Defn('curse', 'molinari')
    wowi_defn = Defn('wowi', '13188-molinari')

    result = await pkg_management.install(iw_config_ctx, [curse_defn], replace_folders=False)
    assert type(result[curse_defn]) is R.PkgInstalled

    result = await pkg_management.install(iw_config_ctx, [wowi_defn], replace_folders=False)
    assert type(result[wowi_defn]) is R.PkgConflictsWithInstalled

    result = await pkg_management.install(iw_config_ctx, [wowi_defn], replace_folders=True)
    assert type(result[wowi_defn]) is R.PkgConflictsWithInstalled


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_install_recognises_renamed_pkg_from_id(
    monkeypatch: pytest.MonkeyPatch,
    iw_aresponses: aresponses.ResponsesMockServer,
    iw_config_ctx: ConfigBoundCtx,
):
    iw_aresponses.add(
        **Route(
            '//api.github.com/repos/p3lim-wow/molinarifico',
            iw_aresponses.Response(status=404),
        ).to_aresponses_add_args()
    )

    old_defn = Defn('github', 'p3lim-wow/molinari')
    new_defn = Defn('github', 'p3lim-wow/molinarifico')

    result = await pkg_management.install(iw_config_ctx, [old_defn], replace_folders=False)
    assert type(result[old_defn]) is R.PkgInstalled

    result = await pkg_management.install(iw_config_ctx, [old_defn], replace_folders=False)
    assert type(result[old_defn]) is R.PkgAlreadyInstalled

    result = await pkg_management.install(iw_config_ctx, [new_defn], replace_folders=False)
    assert type(result[new_defn]) is R.PkgNonexistent

    async def resolve(config_ctx, defns, with_deps=False):
        result = await orig_resolve(config_ctx, [old_defn])
        pkg = attrs.evolve(result[old_defn], slug=new_defn.alias)
        return {new_defn: pkg}

    orig_resolve = pkg_management.resolve
    monkeypatch.setattr(pkg_management, 'resolve', resolve)

    result = await pkg_management.install(iw_config_ctx, [new_defn], replace_folders=False)
    assert type(result[new_defn]) is R.PkgAlreadyInstalled


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_update_lifecycle_with_strategy_switch(iw_config_ctx: ConfigBoundCtx):
    defn = Defn('curse', 'molinari')
    versioned_defn = defn.with_version('100005.97-Release')

    result = (await pkg_management.install(iw_config_ctx, [defn], replace_folders=False))[defn]
    assert type(result) is R.PkgInstalled

    result = (await pkg_management.update(iw_config_ctx, [defn]))[defn]
    assert type(result) is R.PkgUpToDate
    assert result.is_pinned is False

    result = (await pkg_management.update(iw_config_ctx, [versioned_defn]))[versioned_defn]
    assert type(result) is R.PkgUpdated
    assert result.new_pkg.options.version_eq is True

    result = (await pkg_management.update(iw_config_ctx, [defn]))[defn]
    assert type(result) is R.PkgUpToDate
    assert result.is_pinned is True


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_update_reinstalls_corrupted_pkgs(
    iw_config_ctx: ConfigBoundCtx,
):
    defn = Defn('curse', 'molinari')

    results = await pkg_management.install(iw_config_ctx, [defn], replace_folders=False)

    result = results[defn]
    assert type(result) is R.PkgInstalled

    folders = [iw_config_ctx.config.addon_dir / f.name for f in result.pkg.folders]

    first_folder = folders[0]
    first_folder.rename(first_folder.with_name('foo'))
    assert not all(f.is_dir() for f in folders)

    results = await pkg_management.update(iw_config_ctx, [defn])
    assert type(results[defn]) is R.PkgUpdated
    assert all(f.is_dir() for f in folders)


@pytest.mark.parametrize('keep_folders', [True, False])
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_deleting_and_retaining_folders_on_remove(
    iw_config_ctx: ConfigBoundCtx,
    keep_folders: bool,
):
    defn = Defn('curse', 'molinari')

    await pkg_management.install(iw_config_ctx, [defn], replace_folders=False)
    pkg = pkg_management.get_pkg(iw_config_ctx, defn)
    assert pkg

    folders = [iw_config_ctx.config.addon_dir / f.name for f in pkg.folders]
    assert all(f.is_dir() for f in folders)

    results = await pkg_management.remove(iw_config_ctx, [defn], keep_folders=keep_folders)
    assert type(results[defn]) is R.PkgRemoved
    assert not pkg_management.get_pkg(iw_config_ctx, defn)
    if keep_folders:
        assert all(f.is_dir() for f in folders)
    else:
        assert not any(f.is_dir() for f in folders)


@pytest.mark.parametrize('keep_folders', [True, False])
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_removing_pkg_with_missing_folders(
    iw_config_ctx: ConfigBoundCtx,
    keep_folders: bool,
):
    defn = Defn('curse', 'molinari')

    results = await pkg_management.install(iw_config_ctx, [defn], replace_folders=False)

    result = results[defn]
    assert type(result) is R.PkgInstalled

    folders = [iw_config_ctx.config.addon_dir / f.name for f in result.pkg.folders]
    for folder in folders:
        folder.rename(folder.with_name(f'Not_{folder.name}'))
    assert not any(f.is_dir() for f in folders)

    results = await pkg_management.remove(iw_config_ctx, [defn], keep_folders=keep_folders)
    assert type(results[defn]) is R.PkgRemoved
    assert not pkg_management.get_pkg(iw_config_ctx, defn)


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_replace_pkg(
    iw_config_ctx: ConfigBoundCtx,
):
    old_defn = Defn('curse', 'molinari')
    new_defn = Defn('github', 'p3lim-wow/molinari')

    results = await pkg_management.install(iw_config_ctx, [old_defn], replace_folders=False)
    assert type(results[old_defn]) is R.PkgInstalled

    results = await pkg_management.replace(iw_config_ctx, {old_defn: new_defn})
    assert len(results) == 2
    assert type(results[old_defn]) is R.PkgRemoved
    assert type(results[new_defn]) is R.PkgInstalled


async def test_get_changelog_from_empty_data_url(iw_config_ctx: ConfigBoundCtx):
    assert (await pkg_management.get_changelog(iw_config_ctx, 'github', 'data:,')) == ''


async def test_get_changelog_from_url_encoded_data_url(iw_config_ctx: ConfigBoundCtx):
    assert (
        await pkg_management.get_changelog(iw_config_ctx, 'github', 'data:,foo%20bar')
    ) == 'foo bar'


async def test_get_malformed_changelog(iw_config_ctx: ConfigBoundCtx):
    with pytest.raises(ValueError, match='Unsupported URI with scheme'):
        await pkg_management.get_changelog(iw_config_ctx, 'github', '')


async def test_get_changelog_from_file_uri(
    iw_config_ctx: ConfigBoundCtx,
    tmp_path: Path,
):
    changelog = tmp_path / 'changelog.txt'
    changelog.write_text('test')
    assert (
        await pkg_management.get_changelog(iw_config_ctx, 'github', changelog.as_uri())
    ) == 'test'


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_get_changelog_from_web_url(iw_config_ctx: ConfigBoundCtx):
    assert (
        await pkg_management.get_changelog(
            iw_config_ctx,
            'curse',
            'https://api.curseforge.com/v1/mods/20338/files/3657564/changelog',
        )
    ).startswith('<h3>Changes in')
