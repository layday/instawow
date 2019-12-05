import pytest

from instawow.matchers import match_toc_ids, match_dir_names, get_leftovers
from instawow.models import is_pkg


@pytest.fixture(autouse=True)
def addons(manager):
    (manager.config.addon_dir / 'Molinari').mkdir()
    (manager.config.addon_dir / 'Molinari' / 'Molinari.toc').write_text('''\
## X-Curse-Project-ID: 20338
## X-WoWI-ID: 13188
''')


@pytest.mark.asyncio
@pytest.mark.parametrize('test_func', [match_toc_ids, match_dir_names])
async def test_match_on_toc_id_or_dir_name(manager, test_func):
    (folders, results), = await test_func(manager, get_leftovers(manager))
    matches = {(r.origin, r.id) for r in results if is_pkg(r)}
    if manager.config.is_classic:
        assert {('curse', '20338')} == matches
    else:
        assert {('curse', '20338'), ('wowi', '13188')} == matches
