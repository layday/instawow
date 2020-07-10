import pytest

from instawow.resolvers import Defn


@pytest.mark.asyncio
async def test_search(manager):
    results = await manager.search('molinari', limit=5)
    assert Defn('curse', 'molinari') in results and Defn('wowi', '13188-molinari') in results


@pytest.mark.asyncio
async def test_search_with_extra_spice(manager):
    results = await manager.search('AtlasLootClassic', limit=5)
    if manager.config.is_classic:
        assert Defn('curse', 'atlaslootclassic') in results
    else:
        assert Defn('curse', 'atlaslootclassic') not in results
