
import pytest

from instawow.config import Config
from instawow.manager import Manager
from instawow.wa_updater import (AuraEntry, ApiMetadata, WaCompanionBuilder,
                                 URL, bucketise)


@pytest.fixture
def builder(tmp_path):
    addons = tmp_path / 'World of Warcraft/Interface/AddOns'
    addons.mkdir(parents=True)
    config = Config(config_dir=tmp_path / 'config', addon_dir=addons)
    config.write()
    yield WaCompanionBuilder(Manager(config))


@pytest.fixture
def event_loop(builder):
    yield builder.loop


def test_bucketise_bucketises_by_putting_things_in_a_bucketing_bucket():
    assert bucketise(iter([1, 1, 0, 1]), bool) == {True: [1, 1, 1], False: [0]}


@pytest.mark.asyncio
@pytest.mark.parametrize('ids', [['RaidCDs', 'bfaraid2'],
                                 ['bfaraid2', 'RaidCDs'],])
async def test_id_order_is_retained_in_aura_metadata(builder, ids):
    builder.client.set(await builder.client_factory())
    results = await builder.get_wago_aura_metadata(ids)
    assert ids == [r.slug for r in results]


@pytest.mark.asyncio
async def test_id_length_is_retained_in_aura_metadata(builder):
    builder.client.set(await builder.client_factory())
    ids = ['bfaraid2', 'foobar', 'RaidCDs']    # Invalid ID flanked by two valid IDs
    results = await builder.get_wago_aura_metadata(ids)
    assert [ApiMetadata, type(None), ApiMetadata] == [type(r) for r in results]


def test_can_parse_empty_displays_table(builder):
    assert builder.extract_auras_from_lua('''\
WeakAurasSaved = {
    ["displays"] = {
    },
}
''') == {}


def test_urlless_display_is_discarded(builder):
    assert builder.extract_auras_from_lua('''\
WeakAurasSaved = {
    ["displays"] = {
        ["Foo"] = {
            ["bar"] = "baz",
        },
    },
}
''') == {}


def test_can_parse_minimal_wago_display(builder):
    aura = {'id': 'foo',
            'uid': 'foo',
            'parent': None,
            'url': URL('https://wago.io/foo/1'),
            'version': 1,
            'semver': None,
            'ignore_wago_update': False}
    assert builder.extract_auras_from_lua('''\
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
''') == {'foo': [AuraEntry.construct(aura, set(aura))]}


def test_url_host_not_wago_display_is_discarded(builder):
    assert builder.extract_auras_from_lua('''\
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
''') == {}


def test_can_build_addon_without_updates(builder, request):
    builder.builder_dir.mkdir()
    builder.make_addon([])
    request.config.cache.set('orig_checksum', builder.checksum())


def test_build_is_reproducible(builder, request):
    builder.builder_dir.mkdir()
    builder.make_addon([])
    assert request.config.cache.get('orig_checksum', None) == builder.checksum()
