import pytest

from instawow.matchers import get_folders, match_dir_names, match_toc_ids

# TODO: use bespoke fixtures for catalogue


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
    (manager.config.addon_dir / 'Molinari' / 'Molinari.toc').write_text('''\
## X-Curse-Project-ID: 20338
## X-WoWI-ID: 13188
''')


@pytest.mark.asyncio
async def test_invalid_addons_discarded(manager, invalid_addons):
    folders = get_folders(manager)
    assert folders == frozenset()
    assert await match_toc_ids(manager, folders) == []
    assert await match_dir_names(manager, folders) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('test_func', [match_toc_ids, match_dir_names])
async def test_multiple_pkgs_per_addon_contained_in_results(manager, test_func, molinari):
    (_, results), = await test_func(manager, get_folders(manager))
    matches = {(r.source, r.id) for r in results}
    if manager.config.is_classic:
        if test_func == match_toc_ids:
            pytest.xfail('discrepancy between manager and scraper logic')
        assert {('curse', '20338')} == matches
    else:
        assert {('curse', '20338'), ('wowi', '13188')} == matches


@pytest.mark.asyncio
async def test_multiple_pkgs_per_addon_per_source_contained_in_results(manager):
    write_addons(manager, 'AdiBags', 'AdiBags_Config')
    (_, results), = await match_dir_names(manager, get_folders(manager))
    matches = {(r.source, r.id) for r in results}
    assert {('curse', '23350'), ('curse', '333072')} == matches
