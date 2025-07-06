from __future__ import annotations

import pytest

from instawow import config_ctx
from instawow.definitions import Defn
from instawow.matchers import (
    AddonFolder,
    Matcher,
    _match_addon_names_with_folder_names,
    _match_folder_name_subsets,
    _match_toc_source_ids,
    get_unreconciled_folders,
)
from instawow.wow_installations import Track, to_flavour

pytestmark = pytest.mark.usefixtures('_iw_config_ctx', '_iw_web_client_ctx')


def write_addons(
    *addons: str,
):
    config = config_ctx.config()

    for addon in addons:
        (config.addon_dir / addon).mkdir()
        (config.addon_dir / addon / f'{addon}.toc').touch()


def write_masque_addon():
    masque = config_ctx.config().addon_dir / 'Masque'
    masque.mkdir()
    (masque / 'Masque.toc').write_text(
        """\
## X-Curse-Project-ID: 13592
## X-WoWI-ID: 12097
""",
        encoding='utf-8',
    )
    return masque


async def test_can_extract_defns_from_addon_folder_toc():
    addon_folder = AddonFolder.from_path(
        to_flavour(config_ctx.config().track), write_masque_addon()
    )
    assert addon_folder
    assert addon_folder.get_defns_from_toc_keys(
        config_ctx.resolvers().addon_toc_key_and_id_pairs
    ) == {Defn('curse', '13592'), Defn('wowi', '12097')}


async def test_reconcile_invalid_addons_discarded():
    config = config_ctx.config()
    folders = get_unreconciled_folders()

    config.addon_dir.joinpath('foo').mkdir()
    config.addon_dir.joinpath('bar').touch()

    assert folders == frozenset()
    assert await _match_toc_source_ids(folders) == []
    assert await _match_folder_name_subsets(folders) == []


@pytest.mark.parametrize(
    ('test_func', 'expected_defns'),
    [
        (
            _match_toc_source_ids,
            {
                Defn('curse', '13592'),
                Defn('wowi', '12097'),
                Defn('github', '44074003'),
                Defn('wago', 'kRNLgpGo'),
            },
        ),
        (
            _match_folder_name_subsets,
            {
                Defn('curse', '13592'),
                Defn('wowi', '12097'),
            },
        ),
        (
            _match_addon_names_with_folder_names,
            {
                Defn('curse', '13592'),
                Defn('wowi', '12097'),
                Defn('github', '44074003'),
            },
        ),
    ],
)
async def test_reconcile_multiple_defns_per_addon_contained_in_results(
    test_func: Matcher,
    expected_defns: set[Defn],
):
    write_masque_addon()
    ((_, matches),) = await test_func(get_unreconciled_folders())
    assert expected_defns == set(matches)


@pytest.mark.parametrize(
    ('iw_profile_config_values', 'expected_defns'),
    [
        (
            Track.Retail,
            {
                Defn('wowi', '12097'),
                Defn('curse', '13592'),
            },
        ),
        (
            Track.Classic,
            {
                Defn('curse', '13592'),
            },
        ),
        (
            Track.VanillaClassic,
            {
                Defn('wowi', '12097'),
                Defn('curse', '13592'),
            },
        ),
    ],
    indirect=['iw_profile_config_values'],
)
async def test_reconcile_results_vary_by_game_flavour(
    expected_defns: set[Defn],
):
    write_addons('Masque')
    ((_, matches),) = await _match_folder_name_subsets(get_unreconciled_folders())
    assert expected_defns == set(matches)
