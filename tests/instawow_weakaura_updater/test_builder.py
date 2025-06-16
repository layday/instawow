from __future__ import annotations

from pathlib import Path

import pytest
from yarl import URL

from instawow import config_ctx, pkg_management
from instawow.definitions import Defn
from instawow.wow_installations import extract_installation_dir_from_addon_dir
from instawow_weakaura_updater.builder import (
    _Aura,
    _generate_addon,
    _WeakAuras,
    build_addon,
    extract_installed_auras,
)
from instawow_weakaura_updater.config import PluginConfig

pytestmark = pytest.mark.usefixtures('_iw_config_ctx')


@pytest.fixture
async def plugin_config():
    return PluginConfig(profile_config=config_ctx.config()).ensure_dirs()


@pytest.fixture
async def saved_vars_path():
    installation_path = extract_installation_dir_from_addon_dir(
        config_ctx.config().addon_dir,
    )
    assert installation_path
    saved_vars_path = installation_path.joinpath('WTF/Account/Instawow/SavedVariables')
    saved_vars_path.mkdir(parents=True)
    return saved_vars_path


def test_extract_no_saved_vars(
    plugin_config: PluginConfig,
):
    assert list(extract_installed_auras(plugin_config)) == []


def test_extract_empty_displays_table(
    plugin_config: PluginConfig,
    saved_vars_path: Path,
):
    (saved_vars_path / _WeakAuras.name).with_suffix('.lua').write_text(
        """\
WeakAurasSaved = {
    ["displays"] = {
    },
}
""",
        encoding='utf-8',
    )
    assert list(extract_installed_auras(plugin_config)) == [('Instawow', _WeakAuras, {})]


def test_extract_urlless_display(
    plugin_config: PluginConfig,
    saved_vars_path: Path,
):
    (saved_vars_path / _WeakAuras.name).with_suffix('.lua').write_text(
        """\
WeakAurasSaved = {
    ["displays"] = {
        ["Foo"] = {
            ["bar"] = "baz",
        },
    },
}
""",
        encoding='utf-8',
    )
    assert list(extract_installed_auras(plugin_config)) == [('Instawow', _WeakAuras, {})]


def test_extract_url_host_not_wago_display(
    plugin_config: PluginConfig,
    saved_vars_path: Path,
):
    (saved_vars_path / _WeakAuras.name).with_suffix('.lua').write_text(
        """\
WeakAurasSaved = {
    ["displays"] = {
        ["Foo"] = {
            ["bar"] = "baz",
            ["url"] = "https://wafo.io/foo/1",
            ["version"] = 1,
            ["id"] = "foo",
            ["uid"] = "foo",
        },
    },
}
""",
        encoding='utf-8',
    )
    assert list(extract_installed_auras(plugin_config)) == [('Instawow', _WeakAuras, {})]


def test_extract_minimal_wago_display(
    plugin_config: PluginConfig,
    saved_vars_path: Path,
):
    (saved_vars_path / _WeakAuras.name).with_suffix('.lua').write_text(
        """\
WeakAurasSaved = {
    ["displays"] = {
        ["Foo"] = {
            ["bar"] = "baz",
            ["url"] = "https://wago.io/foo/1",
            ["version"] = 1,
            ["id"] = "foo",
            ["uid"] = "foo",
        },
    },
}
""",
        encoding='utf-8',
    )
    assert list(extract_installed_auras(plugin_config)) == [
        (
            'Instawow',
            _WeakAuras,
            {
                'foo': [
                    _Aura(
                        id='foo',
                        uid='foo',
                        parent=None,
                        url=URL('https://wago.io/foo/1'),
                        version=1,
                    )
                ]
            },
        )
    ]


def test_build_addon_no_auras(
    plugin_config: PluginConfig,
):
    _generate_addon(plugin_config, {})


async def test_build_addon_no_wago_auras(
    plugin_config: PluginConfig,
    saved_vars_path: Path,
):
    (saved_vars_path / _WeakAuras.name).with_suffix('.lua').write_text(
        """\
WeakAurasSaved = {
    ["displays"] = {
        ["Foo"] = {
            ["bar"] = "baz",
        },
    },
}
""",
        encoding='utf-8',
    )

    await build_addon(plugin_config)


def test_generate_reproducible(
    plugin_config: PluginConfig,
):
    checksum = _generate_addon(plugin_config, {}).version.read_text(encoding='utf-8')
    assert checksum == _generate_addon(plugin_config, {}).version.read_text(encoding='utf-8')


def test_generate_emits_changelog(
    plugin_config: PluginConfig,
):
    assert _generate_addon(plugin_config, {}).changelog.read_text(encoding='utf-8') == 'n/a'


async def test_resolve_weakauras_companion_pkg(
    plugin_config: PluginConfig,
):
    await build_addon(plugin_config)
    defn = Defn('instawow', 'weakauras-companion')
    resolve_results = await pkg_management.resolve([defn])
    assert type(resolve_results[defn]) is dict


async def test_resolve_weakauras_companion_autoupdate_pkg():
    defn = Defn('instawow', 'weakauras-companion-autoupdate')
    resolve_results = await pkg_management.resolve([defn])
    assert type(resolve_results[defn]) is dict
