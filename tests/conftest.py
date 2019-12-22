import pytest

from instawow.config import Config
from instawow.manager import Manager, init_web_client, prepare_db_session


def pytest_addoption(parser):
    parser.addoption('--vcrpy-mode', action='store', default='none')


@pytest.fixture(scope='session')
def temp_dir(tmp_path_factory):
    yield tmp_path_factory.mktemp('temp', numbered=True)


@pytest.fixture(params=('retail', 'classic'))
def partial_config(tmp_path, request, temp_dir):
    addons = tmp_path / 'addons'
    addons.mkdir()
    return {'addon_dir': addons, 'temp_dir': temp_dir, 'game_flavour': request.param}


@pytest.fixture
def full_config(tmp_path, partial_config):
    return {**partial_config, 'config_dir': tmp_path / 'config'}


@pytest.fixture
async def web_client():
    async with init_web_client() as web_client:
        yield web_client


@pytest.fixture
def manager(full_config, web_client):
    config = Config(**full_config).write()
    db_session = prepare_db_session(config=config)
    manager = Manager(config, db_session)
    manager.web_client = web_client
    yield manager
