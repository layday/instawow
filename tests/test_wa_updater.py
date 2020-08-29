import pytest
from yarl import URL

from instawow.wa_updater import BuilderConfig, WaCompanionBuilder, WeakAura, WeakAuras


@pytest.fixture
def wa_saved_vars(manager):
    saved_vars = (
        manager.config.addon_dir.parents[1] / 'WTF' / 'Account' / 'test' / 'SavedVariables'
    )
    saved_vars.mkdir(parents=True)
    (saved_vars / WeakAuras.Meta.filename).write_text(
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
def builder(manager):
    yield WaCompanionBuilder(manager, BuilderConfig(account='test'))


def test_can_parse_empty_displays_table(builder):
    assert (
        builder.extract_auras(
            WeakAuras,
            '''\
WeakAurasSaved = {
    ["displays"] = {
    },
}
''',
        ).entries
        == {}
    )


def test_urlless_display_is_discarded(builder):
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
        ).entries
        == {}
    )


def test_can_parse_minimal_wago_display(builder):
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
        ).entries
        == {'foo': [aura]}
    )


@pytest.mark.xfail
def test_url_host_not_wago_display_is_discarded(builder):
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
        ).entries
        == {}
    )


def test_can_build_addon_with_empty_seq(builder):
    builder.make_addon([])


@pytest.mark.asyncio
async def test_can_build_addon_with_mock_saved_vars(builder, wa_saved_vars):
    await builder.build()


def test_build_is_reproducible(builder):
    builder.make_addon([])
    checksum = builder.checksum()
    builder.make_addon([])
    assert checksum == builder.checksum()
