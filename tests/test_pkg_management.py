from __future__ import annotations

from pathlib import Path

import aiohttp
import aiohttp.web
import pytest

from instawow import config_ctx, pkg_management
from instawow.definitions import Defn, Strategy
from instawow.results import (
    InternalError,
    PkgAlreadyInstalled,
    PkgConflictsWithInstalled,
    PkgConflictsWithUnreconciled,
    PkgInstalled,
    PkgNonexistent,
    PkgNotInstalled,
    PkgRemoved,
    PkgSourceInvalid,
    PkgStrategiesUnsupported,
    PkgUpdated,
    PkgUpToDate,
)

from ._fixtures.http import AddRoutes, Route

pytestmark = pytest.mark.usefixtures('_iw_config_ctx', '_iw_web_client_ctx')


async def test_pinning_supported_pkg():
    defn = Defn('curse', 'masque')

    install_result = (await pkg_management.install([defn], replace_folders=False))[defn]
    assert type(install_result) is PkgInstalled

    for new_defn in (defn.with_version(install_result.pkg.version), defn):
        pin_result = (await pkg_management.pin([new_defn]))[new_defn]
        assert type(pin_result) is PkgInstalled
        assert pin_result.pkg.options.version_eq is bool(new_defn.strategies[Strategy.VersionEq])
        assert install_result.pkg.version == pin_result.pkg.version


async def test_pinning_unsupported_pkg():
    defn = Defn('wowi', '12097')

    await pkg_management.install([defn], replace_folders=False)
    [installed_pkg] = pkg_management.get_pkgs([defn])
    assert installed_pkg is not None
    assert installed_pkg.options.version_eq is False

    result = (await pkg_management.pin([defn]))[defn]
    assert type(result) is PkgStrategiesUnsupported
    assert result.strategies == {Strategy.VersionEq}
    assert installed_pkg.options.version_eq is False


async def test_pinning_nonexistent_pkg():
    defn = Defn('curse', 'masque')
    result = await pkg_management.pin([defn])
    assert type(result[defn]) is PkgNotInstalled


async def test_pinning_unsupported_nonexistent_pkg():
    defn = Defn('wowi', '12097')
    result = await pkg_management.pin([defn])
    assert type(result[defn]) is PkgStrategiesUnsupported


@pytest.mark.parametrize('exception', [ValueError('foo'), aiohttp.ClientError('bar')])
async def test_resolve_rewraps_exception_from_resolve(
    monkeypatch: pytest.MonkeyPatch,
    exception: Exception,
):
    async def resolve_one(defn, metadata):
        raise exception

    resolvers = config_ctx.resolvers()
    monkeypatch.setattr(resolvers['curse'], 'resolve_one', resolve_one)

    defn = Defn('curse', 'masque')
    result = (await pkg_management.resolve([defn]))[defn]
    assert type(result) is InternalError
    assert str(result) == f'internal error: "{exception}"'


async def test_resolve_invalid_source():
    defn = Defn('bar', 'baz')
    results = await pkg_management.resolve([defn])
    assert type(results[defn]) is PkgSourceInvalid


async def test_resolve_plugin_hook_source():
    pytest.importorskip('instawow_test_plugin')
    defn = Defn('me', 'bar')
    results = await pkg_management.resolve([defn])
    assert type(results[defn]) is dict


async def test_install_can_replace_unreconciled_folders():
    masque = config_ctx.config().addon_dir / 'Masque'
    masque.mkdir()

    defn = Defn('curse', 'masque')

    result = await pkg_management.install([defn], replace_folders=False)
    assert type(result[defn]) is PkgConflictsWithUnreconciled
    assert not any(masque.iterdir())

    result = await pkg_management.install([defn], replace_folders=True)
    assert type(result[defn]) is PkgInstalled
    assert any(masque.iterdir())


async def test_install_cannot_replace_reconciled_folders():
    curse_defn = Defn('curse', 'masque')
    wowi_defn = Defn('wowi', '12097-masque')

    result = await pkg_management.install([curse_defn], replace_folders=False)
    assert type(result[curse_defn]) is PkgInstalled

    result = await pkg_management.install([wowi_defn], replace_folders=False)
    assert type(result[wowi_defn]) is PkgConflictsWithInstalled

    result = await pkg_management.install([wowi_defn], replace_folders=True)
    assert type(result[wowi_defn]) is PkgConflictsWithInstalled


async def test_install_recognises_renamed_pkg_from_id(
    monkeypatch: pytest.MonkeyPatch,
    iw_add_routes: AddRoutes,
):
    iw_add_routes(
        Route(
            r'//api\.github\.com/repos/sfx-wow/masquelicious/?.*',
            lambda: aiohttp.web.Response(status=404),
        )
    )

    old_defn = Defn('github', 'sfx-wow/masque')
    new_defn = Defn('github', 'sfx-wow/masquelicious')

    result = await pkg_management.install([old_defn], replace_folders=False)
    assert type(result[old_defn]) is PkgInstalled

    result = await pkg_management.install([old_defn], replace_folders=False)
    assert type(result[old_defn]) is PkgAlreadyInstalled

    result = await pkg_management.install([new_defn], replace_folders=False)
    assert type(result[new_defn]) is PkgNonexistent

    old_resolve = pkg_management.resolve

    async def new_resolve(defns, with_deps=False):
        result = await old_resolve([old_defn])
        pkg_candidate = result[old_defn]
        assert type(pkg_candidate) is dict
        return {new_defn: pkg_candidate | {'slug': new_defn.alias}}

    monkeypatch.setattr(pkg_management, 'resolve', new_resolve)

    result = await pkg_management.install([new_defn], replace_folders=False)
    assert type(result[new_defn]) is PkgAlreadyInstalled


async def test_update_lifecycle_with_strategy_switch():
    defn = Defn('curse', 'masque')
    versioned_defn = defn.with_version('11.0.2')

    result = (await pkg_management.install([defn], replace_folders=False))[defn]
    assert type(result) is PkgInstalled

    result = (await pkg_management.update([defn]))[defn]
    assert type(result) is PkgUpToDate
    assert result.is_pinned is False

    result = (await pkg_management.update([versioned_defn]))[versioned_defn]
    assert type(result) is PkgUpdated
    assert result.new_pkg.options.version_eq is True

    result = (await pkg_management.update([defn]))[defn]
    assert type(result) is PkgUpToDate
    assert result.is_pinned is True


async def test_update_reinstalls_corrupted_pkgs():
    defn = Defn('curse', 'masque')

    results = await pkg_management.install([defn], replace_folders=False)

    result = results[defn]
    assert type(result) is PkgInstalled

    folders = [config_ctx.config().addon_dir / f.name for f in result.pkg.folders]

    first_folder = folders[0]
    first_folder.rename(first_folder.with_name('foo'))
    assert not all(f.is_dir() for f in folders)

    results = await pkg_management.update([defn])
    assert type(results[defn]) is PkgUpdated
    assert all(f.is_dir() for f in folders)


@pytest.mark.parametrize('keep_folders', [True, False])
async def test_deleting_and_retaining_folders_on_remove(
    keep_folders: bool,
):
    defn = Defn('curse', 'masque')

    await pkg_management.install([defn], replace_folders=False)
    [pkg] = pkg_management.get_pkgs([defn])
    assert pkg

    folders = [config_ctx.config().addon_dir / f.name for f in pkg.folders]
    assert all(f.is_dir() for f in folders)

    results = await pkg_management.remove([defn], keep_folders=keep_folders)
    assert type(results[defn]) is PkgRemoved
    [pkg] = pkg_management.get_pkgs([defn])
    assert not pkg
    if keep_folders:
        assert all(f.is_dir() for f in folders)
    else:
        assert not any(f.is_dir() for f in folders)


@pytest.mark.parametrize('keep_folders', [True, False])
async def test_removing_pkg_with_missing_folders(
    keep_folders: bool,
):
    defn = Defn('curse', 'masque')

    results = await pkg_management.install([defn], replace_folders=False)

    result = results[defn]
    assert type(result) is PkgInstalled

    folders = [config_ctx.config().addon_dir / f.name for f in result.pkg.folders]
    for folder in folders:
        folder.rename(folder.with_name(f'Not_{folder.name}'))
    assert not any(f.is_dir() for f in folders)

    results = await pkg_management.remove([defn], keep_folders=keep_folders)
    assert type(results[defn]) is PkgRemoved
    [pkg] = pkg_management.get_pkgs([defn])
    assert not pkg


async def test_replace_pkg():
    old_defn = Defn('curse', 'masque')
    new_defn = Defn('github', 'sfx-wow/masque')

    results = await pkg_management.install([old_defn], replace_folders=False)
    assert type(results[old_defn]) is PkgInstalled

    results = await pkg_management.replace({old_defn: new_defn})
    assert len(results) == 2
    assert type(results[old_defn]) is PkgRemoved
    assert type(results[new_defn]) is PkgInstalled


async def test_get_changelog_from_empty_data_url():
    assert (await pkg_management.get_changelog('github', 'data:,')) == ''


async def test_get_changelog_from_url_encoded_data_url():
    assert (await pkg_management.get_changelog('github', 'data:,foo%20bar')) == 'foo bar'


async def test_get_malformed_changelog():
    with pytest.raises(ValueError, match='Unsupported URI with scheme'):
        await pkg_management.get_changelog('github', '')


async def test_get_changelog_from_file_uri(
    tmp_path: Path,
):
    changelog = tmp_path / 'changelog.txt'
    changelog.write_text('test', encoding='utf-8')
    assert (await pkg_management.get_changelog('github', changelog.as_uri())) == 'test'


async def test_get_changelog_from_web_url():
    assert (
        await pkg_management.get_changelog(
            'curse',
            'https://api.curseforge.com/v1/mods/13592/files/6454541/changelog',
        )
    ).startswith('<h2>11.1.5</h2>')
