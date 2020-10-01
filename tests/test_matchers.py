import pytest

from instawow.matchers import (
    AddonFolder,
    get_folder_set,
    match_dir_names,
    match_toc_ids,
    match_toc_names,
)
from instawow.resolvers import Defn
from instawow.utils import TocReader


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
    molinari_folder = manager.config.addon_dir / 'Molinari'
    molinari_folder.mkdir()
    (molinari_folder / 'Molinari.toc').write_text(
        '''\
## X-Curse-Project-ID: 20338
## X-WoWI-ID: 13188
'''
    )
    yield molinari_folder


def test_addon_folder_is_comparable_to_str(molinari):
    addon_folder = AddonFolder(molinari.name, None)
    assert isinstance(addon_folder, AddonFolder) and addon_folder <= 'Molinari'


def test_addon_folder_can_extract_defns_frm_toc(molinari):
    addon_folder = AddonFolder(molinari.name, TocReader.from_parent_folder(molinari))
    assert addon_folder.defns_from_toc == frozenset(
        [Defn('curse', '20338'), Defn('wowi', '13188')]
    )


@pytest.mark.asyncio
async def test_invalid_addons_discarded(manager, invalid_addons):
    folders = get_folder_set(manager)
    assert folders == frozenset()
    assert await match_toc_ids(manager, folders) == []
    assert await match_dir_names(manager, folders) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('test_func', [match_toc_ids, match_toc_names, match_dir_names])
async def test_multiple_defns_per_addon_contained_in_results(manager, molinari, test_func):
    ((_, matches),) = await test_func(manager, get_folder_set(manager))
    assert {Defn('curse', '20338'), Defn('wowi', '13188')} == set(matches)


@pytest.mark.asyncio
async def test_multiple_defns_per_addon_per_source_contained_in_results(manager):
    write_addons(manager, 'AdiBags', 'AdiBags_Config')
    ((_, matches),) = await match_dir_names(manager, get_folder_set(manager))
    assert {Defn('curse', '23350'), Defn('curse', '333072')} == set(matches)
