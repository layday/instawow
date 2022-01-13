from __future__ import annotations

import pytest
from yarl import URL

from instawow.manager import Manager
from instawow.models import Pkg
from instawow.resolvers import Defn
from instawow.wa_updater import WaCompanionBuilder, WeakAura, WeakAuras


@pytest.fixture
def wa_saved_vars(iw_manager: Manager):
    saved_vars = (
        iw_manager.config.addon_dir.parents[1] / 'WTF' / 'Account' / 'test' / 'SavedVariables'
    )
    saved_vars.mkdir(parents=True)
    (saved_vars / WeakAuras.filename).write_text(
        '''\
WeakAurasSaved = {
    ["displays"] = {
        ["Foo"] = {
            ["bar"] = "baz",
        },
    },
}
'''
    )


@pytest.fixture
def builder(iw_manager: Manager):
    yield WaCompanionBuilder(iw_manager)


def test_can_parse_empty_displays_table(builder: WaCompanionBuilder):
    assert (
        builder.extract_auras(
            WeakAuras,
            '''\
WeakAurasSaved = {
    ["displays"] = {
    },
}
''',
        ).__root__
        == {}
    )


def test_urlless_display_is_discarded(builder: WaCompanionBuilder):
    assert (
        builder.extract_auras(
            WeakAuras,
            '''\
WeakAurasSaved = {
    ["displays"] = {
        ["Foo"] = {
            ["bar"] = "baz",
        },
    },
}
''',
        ).__root__
        == {}
    )


def test_can_parse_minimal_wago_display(builder: WaCompanionBuilder):
    aura = WeakAura(
        id='foo',
        uid='foo',
        parent=None,
        url=URL('https://wago.io/foo/1'),
        version=1,
    )
    assert (
        builder.extract_auras(
            WeakAuras,
            '''\
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
''',
        ).__root__
        == {'foo': [aura]}
    )


def test_url_host_not_wago_display_is_discarded(builder: WaCompanionBuilder):
    assert (
        builder.extract_auras(
            WeakAuras,
            '''\
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
''',
        ).__root__
        == {}
    )


def test_can_build_addon_with_empty_seq(builder: WaCompanionBuilder):
    builder._generate_addon([])


async def test_can_build_addon_with_mock_saved_vars(
    builder: WaCompanionBuilder, wa_saved_vars: None
):
    await builder.build()


def test_build_is_reproducible(builder: WaCompanionBuilder):
    builder._generate_addon([])
    checksum = builder._checksum()
    builder._generate_addon([])
    assert checksum == builder._checksum()


def test_changelog_is_generated(builder: WaCompanionBuilder):
    builder._generate_addon([])
    assert builder.changelog_path.read_text() == 'n/a'


async def test_can_resolve_wa_companion_pkg(builder: WaCompanionBuilder):
    await builder.build()
    defn = Defn('instawow', 'weakauras-companion')
    resolve_results = await builder.manager.resolve([defn])
    assert type(resolve_results[defn]) is Pkg


async def test_can_resolve_wa_companion_autoupdate_pkg(builder: WaCompanionBuilder):
    defn = Defn('instawow', 'weakauras-companion-autoupdate')
    resolve_results = await builder.manager.resolve([defn])
    assert type(resolve_results[defn]) is Pkg
