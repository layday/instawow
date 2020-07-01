import pytest
from yarl import URL

from instawow.wa_updater import ApiMetadata, WaCompanionBuilder, WeakAura, WeakAuras


@pytest.fixture
def builder(manager):
    yield WaCompanionBuilder(manager, 'test')


@pytest.mark.skip
@pytest.mark.asyncio
@pytest.mark.parametrize('ids', [['RaidCDs', 'bfaraid2'], ['bfaraid2', 'RaidCDs']])
async def test_id_order_is_retained_in_aura_metadata(builder, ids):
    results = await builder.get_wago_aura_metadata(ids)
    assert ids == [r.slug for r in results]


@pytest.mark.skip
@pytest.mark.asyncio
async def test_id_length_is_retained_in_aura_metadata(builder):
    ids = ['bfaraid2', 'foobar', 'RaidCDs']  # Invalid ID flanked by two valid IDs
    results = await builder.get_wago_aura_metadata(ids)
    assert [ApiMetadata, type(None), ApiMetadata] == [type(r) for r in results]


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
        semver=None,
        ignore_wago_update=False,
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


def test_can_build_addon_without_updates(builder):
    builder.make_addon([])


def test_build_is_reproducible(builder):
    builder.make_addon([])
    checksum = builder.checksum()
    builder.make_addon([])
    assert checksum == builder.checksum()
