
import pytest

from instawow.config import Config
from instawow.manager import Manager, init_web_client


@pytest.fixture(params=('retail', 'classic'))
def partial_config(tmp_path, request):
    addons = tmp_path / 'addons'
    addons.mkdir()
    return {'addon_dir': addons, 'game_flavour': request.param}


@pytest.fixture
def full_config(tmp_path, partial_config):
    return {**partial_config, 'config_dir': tmp_path / 'config'}


@pytest.fixture
async def web_client():
    web_client_ = await init_web_client()
    yield lambda: web_client_
    await web_client_.close()


@pytest.fixture
def manager(full_config, web_client):
    manager = Manager(Config(**full_config).write())
    manager._web_client = web_client
    yield manager
