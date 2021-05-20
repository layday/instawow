import pytest

from instawow.config import Flavour
from instawow.matchers import (
    AddonFolder,
    get_unreconciled_folder_set,
    match_addon_names_with_folder_names,
    match_folder_name_subsets,
    match_toc_source_ids,
)
from instawow.resolvers import Defn
from instawow.utils import TocReader


def write_addons(iw_manager, *addons):
    for addon in addons:
        (iw_manager.config.addon_dir / addon).mkdir()
        (iw_manager.config.addon_dir / addon / f'{addon}.toc').touch()


@pytest.fixture
def invalid_addons(iw_manager):
    (iw_manager.config.addon_dir / 'foo').mkdir()
    (iw_manager.config.addon_dir / 'bar').touch()


@pytest.fixture
def molinari(iw_manager):
    molinari_folder = iw_manager.config.addon_dir / 'Molinari'
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


def test_addon_folder_can_extract_defns_from_toc(molinari):
    addon_folder = AddonFolder(molinari.name, TocReader.from_addon_path(molinari))
    assert addon_folder.defns_from_toc == {Defn('curse', '20338'), Defn('wowi', '13188')}


@pytest.mark.asyncio
async def test_invalid_addons_discarded(iw_manager, invalid_addons):
    folders = get_unreconciled_folder_set(iw_manager)
    assert folders == frozenset()
    assert await match_toc_source_ids(iw_manager, folders) == []
    assert await match_folder_name_subsets(iw_manager, folders) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'test_func',
    [match_toc_source_ids, match_addon_names_with_folder_names, match_folder_name_subsets],
)
async def test_multiple_defns_per_addon_contained_in_results(iw_manager, molinari, test_func):
    ((_, matches),) = await test_func(iw_manager, get_unreconciled_folder_set(iw_manager))
    assert {Defn('curse', '20338'), Defn('wowi', '13188')} == set(matches)


@pytest.mark.asyncio
async def test_results_vary_by_game_flavour(iw_manager):
    write_addons(iw_manager, 'AdiBags', 'AdiBags_Config')
    ((_, matches),) = await match_folder_name_subsets(
        iw_manager, get_unreconciled_folder_set(iw_manager)
    )
    if iw_manager.config.game_flavour is Flavour.retail:
        assert {
            Defn('curse', '23350'),
            Defn('curse', '333072'),
            Defn('curse', '431557'),
        } == set(matches)
    elif iw_manager.config.game_flavour is Flavour.vanilla_classic:
        assert {Defn('curse', '23350'), Defn('curse', '333072')} == set(matches)
    else:
        assert False
