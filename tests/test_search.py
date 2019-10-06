import pytest

from instawow.resolvers import Strategies


strategy = Strategies.default


@pytest.mark.asyncio
async def test_search_basic_flavour(manager):
    results = await manager.search('molinari', limit=5)
    assert ('curse', 'molinari', strategy) in results
    if manager.config.is_classic:
        assert ('wowi', '13188-molinari', strategy) not in results
    else:
        assert ('wowi', '13188-molinari', strategy) in results
