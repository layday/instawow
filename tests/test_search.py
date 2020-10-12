import pytest

from instawow.resolvers import Defn


@pytest.fixture(autouse=True)
def mock(mock_all):
    pass


@pytest.mark.asyncio
async def test_search_unfiltered(manager):
    results = await manager.search('molinari', limit=5)
    assert {Defn('curse', 'molinari'), Defn('wowi', '13188-molinari')} == set(results)


@pytest.mark.asyncio
async def test_search_filtered(manager):
    results = await manager.search('molinari', limit=5, sources={'curse'})
    assert {Defn('curse', 'molinari')} == set(results)


@pytest.mark.asyncio
async def test_search_caters_to_flavour(manager):
    results = await manager.search('AtlasLootClassic', limit=5)
    if manager.config.is_classic:
        assert Defn('curse', 'atlaslootclassic') in results
    else:
        assert Defn('curse', 'atlaslootclassic') not in results
