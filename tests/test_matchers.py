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
from instawow.wow_installations import Flavour

pytestmark = pytest.mark.usefixtures('_iw_config_ctx', '_iw_web_client_ctx')


MOLINARI_HASH = '2da096db5769138b5428a068343cddf3'


def write_addons(
    *addons: str,
):
    config = config_ctx.config()

    for addon in addons:
        (config.addon_dir / addon).mkdir()
        (config.addon_dir / addon / f'{addon}.toc').touch()


def write_molinari_addon():
    molinari = config_ctx.config().addon_dir / 'Molinari'
    molinari.mkdir()
    (molinari / 'Molinari.toc').write_text(
        """\
## X-Curse-Project-ID: 20338
## X-WoWI-ID: 13188
""",
        encoding='utf-8',
    )
    return molinari


async def test_can_extract_defns_from_addon_folder_toc():
    addon_folder = AddonFolder.from_path(config_ctx.config().game_flavour, write_molinari_addon())
    assert addon_folder
    assert addon_folder.get_defns_from_toc_keys(
        config_ctx.resolvers().addon_toc_key_and_id_pairs
    ) == {Defn('curse', '20338'), Defn('wowi', '13188')}


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
                Defn('curse', '20338'),
                Defn('wowi', '13188'),
                Defn('github', '388670'),
                Defn('wago', 'WqKQQEKx'),
            },
        ),
        (
            _match_folder_name_subsets,
            {
                Defn('curse', '20338'),
                Defn('wowi', '13188'),
            },
        ),
        (
            _match_addon_names_with_folder_names,
            {
                Defn('curse', '20338'),
                Defn('wowi', '13188'),
                Defn('github', '388670'),
            },
        ),
    ],
)
async def test_reconcile_multiple_defns_per_addon_contained_in_results(
    test_func: Matcher,
    expected_defns: set[Defn],
):
    write_molinari_addon()
    ((_, matches),) = await test_func(get_unreconciled_folders())
    assert expected_defns == set(matches)


@pytest.mark.parametrize(
    ('iw_profile_config_values', 'expected_defns'),
    [
        (
            Flavour.Retail,
            {
                Defn('curse', '23350'),
                Defn('curse', '333072'),
                Defn('curse', '431557'),
                Defn('curse', '674779'),
                Defn('curse', '912615'),
            },
        ),
        (
            Flavour.Classic,
            {
                Defn('curse', '23350'),
            },
        ),
        (
            Flavour.VanillaClassic,
            {
                Defn('curse', '23350'),
                Defn('curse', '333072'),
                Defn('curse', '674779'),
                Defn('curse', '912615'),
            },
        ),
    ],
    indirect=['iw_profile_config_values'],
)
async def test_reconcile_results_vary_by_game_flavour(
    expected_defns: set[Defn],
):
    write_addons('AdiBags', 'AdiBags_Config')
    ((_, matches),) = await _match_folder_name_subsets(get_unreconciled_folders())
    assert expected_defns == set(matches)
