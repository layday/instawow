from __future__ import annotations

from pathlib import Path

import pytest

from instawow.definitions import Defn
from instawow.matchers import (
    AddonFolder,
    Matcher,
    get_unreconciled_folders,
    match_addon_names_with_folder_names,
    match_folder_name_subsets,
    match_toc_source_ids,
)
from instawow.shared_ctx import ConfigBoundCtx
from instawow.wow_installations import Flavour

MOLINARI_HASH = '2da096db5769138b5428a068343cddf3'


def write_addons(
    iw_config_ctx: ConfigBoundCtx,
    *addons: str,
):
    for addon in addons:
        (iw_config_ctx.config.addon_dir / addon).mkdir()
        (iw_config_ctx.config.addon_dir / addon / f'{addon}.toc').touch()


@pytest.fixture
def molinari(
    iw_config_ctx: ConfigBoundCtx,
):
    molinari_folder = iw_config_ctx.config.addon_dir / 'Molinari'
    molinari_folder.mkdir()

    with open(molinari_folder / 'Molinari.toc', 'w', newline='\n') as toc_file:
        toc_file.write(
            """\
## X-Curse-Project-ID: 20338
## X-WoWI-ID: 13188
""",
        )

    return molinari_folder


def test_can_extract_defns_from_addon_folder_toc(
    iw_config_ctx: ConfigBoundCtx,
    molinari: Path,
):
    addon_folder = AddonFolder.from_path(iw_config_ctx.config.game_flavour, molinari)
    assert addon_folder
    assert addon_folder.get_defns_from_toc_keys(
        iw_config_ctx.resolvers.addon_toc_key_and_id_pairs
    ) == {Defn('curse', '20338'), Defn('wowi', '13188')}


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_reconcile_invalid_addons_discarded(
    iw_config_ctx: ConfigBoundCtx,
):
    iw_config_ctx.config.addon_dir.joinpath('foo').mkdir()
    iw_config_ctx.config.addon_dir.joinpath('bar').touch()
    folders = get_unreconciled_folders(iw_config_ctx)
    assert folders == frozenset()
    assert await match_toc_source_ids(iw_config_ctx, folders) == []
    assert await match_folder_name_subsets(iw_config_ctx, folders) == []


@pytest.mark.parametrize(
    ('test_func', 'expected_defns'),
    [
        (
            match_toc_source_ids,
            {
                Defn('curse', '20338'),
                Defn('wowi', '13188'),
                Defn('github', '388670'),
                Defn('wago', 'WqKQQEKx'),
            },
        ),
        (
            match_folder_name_subsets,
            {
                Defn('curse', '20338'),
                Defn('wowi', '13188'),
            },
        ),
        (
            match_addon_names_with_folder_names,
            {
                Defn('curse', '20338'),
                Defn('wowi', '13188'),
                Defn('github', '388670'),
            },
        ),
    ],
)
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_reconcile_multiple_defns_per_addon_contained_in_results(
    iw_config_ctx: ConfigBoundCtx,
    molinari: Path,
    test_func: Matcher,
    expected_defns: set[Defn],
):
    ((_, matches),) = await test_func(iw_config_ctx, get_unreconciled_folders(iw_config_ctx))
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
                Defn('curse', '674779'),
                Defn('curse', '912615'),
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
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_reconcile_results_vary_by_game_flavour(
    iw_config_ctx: ConfigBoundCtx,
    expected_defns: set[Defn],
):
    write_addons(iw_config_ctx, 'AdiBags', 'AdiBags_Config')
    ((_, matches),) = await match_folder_name_subsets(
        iw_config_ctx, get_unreconciled_folders(iw_config_ctx)
    )
    assert expected_defns == set(matches)
