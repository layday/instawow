import pytest

from instawow.resolvers import Strategies

strategy = Strategies.default


@pytest.mark.asyncio
async def test_search(manager):
    results = await manager.search('molinari', limit=5)
    assert (('curse', 'molinari', strategy) in results
            and ('wowi', '13188-molinari', strategy) in results)


@pytest.mark.asyncio
async def test_search_with_extra_spice(manager):
    results = await manager.search('AtlasLootClassic', limit=5)
    if manager.config.is_classic:
        assert ('curse', 'atlaslootclassic', strategy) in results
    else:
        assert ('curse', 'atlaslootclassic', strategy) not in results
