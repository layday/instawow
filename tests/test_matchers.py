import pytest

from instawow.matchers import get_folders, match_dir_names, match_toc_ids, match_toc_names
from instawow.resolvers import Defn


@pytest.fixture(autouse=True)
def mock(mock_all):
    pass


def write_addons(manager, *addons):
    for addon in addons:
        (manager.config.addon_dir / addon).mkdir()
        (manager.config.addon_dir / addon / f'{addon}.toc').touch()


@pytest.fixture
def invalid_addons(manager):
    (manager.config.addon_dir / 'foo').mkdir()
    (manager.config.addon_dir / 'bar').touch()


@pytest.fixture
def molinari(manager):
    (manager.config.addon_dir / 'Molinari').mkdir()
    (manager.config.addon_dir / 'Molinari' / 'Molinari.toc').write_text(
        '''\
## X-Curse-Project-ID: 20338
## X-WoWI-ID: 13188
'''
    )


@pytest.mark.asyncio
async def test_invalid_addons_discarded(manager, invalid_addons):
    folders = get_folders(manager)
    assert folders == frozenset()
    assert await match_toc_ids(manager, folders) == []
    assert await match_dir_names(manager, folders) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('test_func', [match_toc_ids, match_toc_names, match_dir_names])
async def test_multiple_defns_per_addon_contained_in_results(manager, molinari, test_func):
    ((_, matches),) = await test_func(manager, get_folders(manager))
    assert {Defn.get('curse', '20338'), Defn.get('wowi', '13188')} == set(matches)


@pytest.mark.asyncio
async def test_multiple_defns_per_addon_per_source_contained_in_results(manager):
    write_addons(manager, 'AdiBags', 'AdiBags_Config')
    ((_, matches),) = await match_dir_names(manager, get_folders(manager))
    assert {Defn.get('curse', '23350'), Defn.get('curse', '333072')} == set(matches)
