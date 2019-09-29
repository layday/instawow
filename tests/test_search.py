import pytest


@pytest.mark.asyncio
async def test_search_basic_flavour(manager):
    results = await manager.search('molinari', limit=5)
    assert ('curse', 'molinari') in results
    if manager.config.is_classic:
        assert ('wowi', '13188-molinari') not in results
    else:
        assert ('wowi', '13188-molinari') in results
