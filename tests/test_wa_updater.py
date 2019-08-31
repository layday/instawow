
import pytest
from yarl import URL

from instawow.config import Config
from instawow.manager import Manager
from instawow.wa_updater import WaCompanionBuilder, AuraEntry, ApiMetadata


@pytest.fixture
def builder(full_config):
    manager = Manager(config=Config(**full_config).write())
    yield WaCompanionBuilder(manager)


@pytest.fixture
async def web_client(builder):
    builder.web_client = await builder.web_client_factory()
    yield
    await builder.web_client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('ids', [['RaidCDs', 'bfaraid2'],
                                 ['bfaraid2', 'RaidCDs'],])
async def test_id_order_is_retained_in_aura_metadata(builder, web_client, ids):
    results = await builder.get_wago_aura_metadata(ids)
    assert ids == [r.slug for r in results]


@pytest.mark.asyncio
async def test_id_length_is_retained_in_aura_metadata(builder, web_client):
    ids = ['bfaraid2', 'foobar', 'RaidCDs']    # Invalid ID flanked by two valid IDs
    results = await builder.get_wago_aura_metadata(ids)
    assert [ApiMetadata, type(None), ApiMetadata] == [type(r) for r in results]


def test_can_parse_empty_displays_table(builder):
    assert builder.extract_auras('''\
WeakAurasSaved = {
    ["displays"] = {
    },
}
''') == {}


def test_urlless_display_is_discarded(builder):
    assert builder.extract_auras('''\
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
    assert builder.extract_auras('''\
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
    assert builder.extract_auras('''\
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
