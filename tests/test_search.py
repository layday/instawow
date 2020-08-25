import pytest

from instawow.resolvers import Defn


@pytest.fixture(autouse=True)
def mock(mock_all):
    pass


@pytest.mark.asyncio
async def test_search(manager):
    results = await manager.search('molinari', limit=5)
    assert (
        Defn.get('curse', 'molinari') in results and Defn.get('wowi', '13188-molinari') in results
    )


@pytest.mark.asyncio
async def test_search_with_extra_spice(manager):
    results = await manager.search('AtlasLootClassic', limit=5)
    if manager.config.is_classic:
        assert Defn.get('curse', 'atlaslootclassic') in results
    else:
        assert Defn.get('curse', 'atlaslootclassic') not in results
