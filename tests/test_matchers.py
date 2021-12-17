from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest

from instawow.common import Flavour
from instawow.manager import Manager
from instawow.matchers import (
    AddonFolder,
    FolderAndDefnPairs,
    get_unreconciled_folder_set,
    match_addon_names_with_folder_names,
    match_folder_name_subsets,
    match_toc_source_ids,
)
from instawow.resolvers import Defn
from instawow.utils import TocReader


def write_addons(iw_manager: Manager, *addons: str):
    for addon in addons:
        (iw_manager.config.addon_dir / addon).mkdir()
        (iw_manager.config.addon_dir / addon / f'{addon}.toc').touch()


@pytest.fixture
def invalid_addons(iw_manager: Manager):
    (iw_manager.config.addon_dir / 'foo').mkdir()
    (iw_manager.config.addon_dir / 'bar').touch()


@pytest.fixture
def molinari(iw_manager: Manager):
    molinari_folder = iw_manager.config.addon_dir / 'Molinari'
    molinari_folder.mkdir()
    (molinari_folder / 'Molinari.toc').write_text(
        '''\
## X-Curse-Project-ID: 20338
## X-WoWI-ID: 13188
'''
    )
    yield molinari_folder


def test_reconcile_addon_folder_is_comparable_to_str(molinari: Path):
    addon_folder = AddonFolder(molinari.name, TocReader.from_addon_path(molinari))
    assert isinstance(addon_folder, AddonFolder) and addon_folder <= 'Molinari'


def test_reconcile_addon_folder_can_extract_defns_from_toc(molinari: Path):
    addon_folder = AddonFolder(molinari.name, TocReader.from_addon_path(molinari))
    assert addon_folder.defns_from_toc == {Defn('curse', '20338'), Defn('wowi', '13188')}


@pytest.mark.asyncio
async def test_reconcile_invalid_addons_discarded(iw_manager: Manager, invalid_addons: None):
    folders = get_unreconciled_folder_set(iw_manager)
    assert folders == frozenset()
    assert await match_toc_source_ids(iw_manager, folders) == []
    assert await match_folder_name_subsets(iw_manager, folders) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    'test_func',
    [match_toc_source_ids, match_folder_name_subsets, match_addon_names_with_folder_names],
)
async def test_reconcile_multiple_defns_per_addon_contained_in_results(
    iw_manager: Manager,
    molinari: Path,
    test_func: Callable[[Manager, frozenset[AddonFolder]], Awaitable[FolderAndDefnPairs]],
):
    ((_, matches),) = await test_func(iw_manager, get_unreconciled_folder_set(iw_manager))
    expected = {Defn('curse', '20338'), Defn('wowi', '13188')}
    if test_func is match_addon_names_with_folder_names:
        expected.add(Defn('github', 'p3lim-wow/Molinari'))
    assert expected == set(matches)


@pytest.mark.asyncio
async def test_reconcile_results_vary_by_game_flavour(iw_manager: Manager):
    write_addons(iw_manager, 'AdiBags', 'AdiBags_Config')
    ((_, matches),) = await match_folder_name_subsets(
        iw_manager, get_unreconciled_folder_set(iw_manager)
    )
    if iw_manager.config.game_flavour is Flavour.retail:
        assert {
            Defn('curse', '23350'),
            Defn('curse', '333072'),
            Defn('curse', '431557'),
            Defn('wowi', '26025'),
        } == set(matches)
    elif iw_manager.config.game_flavour in {
        Flavour.vanilla_classic,
        Flavour.burning_crusade_classic,
    }:
        assert {
            Defn('curse', '23350'),
            Defn('curse', '333072'),
            Defn('wowi', '26025'),
        } == set(matches)
    else:
        assert False
