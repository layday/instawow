from __future__ import annotations

import pytest
from yarl import URL

from instawow import config_ctx, pkg_management
from instawow.definitions import Defn
from instawow_wa_updater._config import PluginConfig
from instawow_wa_updater._core import Aura, WaCompanionBuilder, WeakAuras, _extract_auras

pytestmark = pytest.mark.usefixtures('_iw_config_ctx')


@pytest.fixture
async def builder():
    return WaCompanionBuilder(
        PluginConfig(config_ctx.config()).ensure_dirs(),
    )


def test_can_parse_empty_displays_table():
    assert (
        _extract_auras(
            WeakAuras,
            """\
WeakAurasSaved = {
    ["displays"] = {
    },
}
""",
        ).auras
        == {}
    )


def test_urlless_display_is_discarded():
    assert (
        _extract_auras(
            WeakAuras,
            """\
WeakAurasSaved = {
    ["displays"] = {
        ["Foo"] = {
            ["bar"] = "baz",
        },
    },
}
""",
        ).auras
        == {}
    )


def test_can_parse_minimal_wago_display():
    aura = Aura(
        id='foo',
        uid='foo',
        parent=None,
        url=URL('https://wago.io/foo/1'),
        version=1,
    )
    assert _extract_auras(
        WeakAuras,
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
    ).auras == {'foo': [aura]}


def test_url_host_not_wago_display_is_discarded():
    assert (
        _extract_auras(
            WeakAuras,
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
        ).auras
        == {}
    )


def test_can_build_addon_with_empty_seq(
    builder: WaCompanionBuilder,
):
    builder._generate_addon([])


async def test_can_build_addon_with_mock_saved_vars(
    builder: WaCompanionBuilder,
):
    saved_vars = (
        config_ctx.config().addon_dir.parents[1] / 'WTF' / 'Account' / 'test' / 'SavedVariables'
    )
    saved_vars.mkdir(parents=True)
    (saved_vars / WeakAuras.addon_name).with_suffix('.lua').write_text(
        """\
WeakAurasSaved = {
    ["displays"] = {
        ["Foo"] = {
            ["bar"] = "baz",
        },
    },
}
"""
    )

    await builder.build()


def test_build_is_reproducible(
    builder: WaCompanionBuilder,
):
    builder._generate_addon([])
    checksum = builder.build_paths.version.read_text(encoding='utf-8')
    builder._generate_addon([])
    assert checksum == builder.build_paths.version.read_text(encoding='utf-8')


def test_changelog_is_generated(
    builder: WaCompanionBuilder,
):
    builder._generate_addon([])
    assert builder.build_paths.changelog.read_text() == 'n/a'


async def test_can_resolve_wa_companion_pkg(
    builder: WaCompanionBuilder,
):
    await builder.build()
    defn = Defn('instawow', 'weakauras-companion')
    resolve_results = await pkg_management.resolve([defn])
    assert type(resolve_results[defn]) is dict


async def test_can_resolve_wa_companion_autoupdate_pkg():
    defn = Defn('instawow', 'weakauras-companion-autoupdate')
    resolve_results = await pkg_management.resolve([defn])
    assert type(resolve_results[defn]) is dict
