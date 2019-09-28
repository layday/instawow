from pathlib import Path

import pytest
import vcr

from instawow.config import Config
from instawow.manager import Manager, prepare_db_session, init_web_client


def pytest_addoption(parser):
    parser.addoption('--vcrpy-mode', action='store', default='none')


@pytest.fixture(params=('retail', 'classic'))
def partial_config(tmp_path, request):
    addons = tmp_path / 'addons'
    addons.mkdir()
    return {'addon_dir': addons, 'temp_dir': tmp_path / 'temp', 'game_flavour': request.param}


@pytest.fixture
def full_config(tmp_path, partial_config):
    return {**partial_config, 'config_dir': tmp_path / 'config'}


@pytest.fixture(autouse=True, scope='module')
def cassette(request):
    path = Path(__file__).parent / 'cassettes' / f'{request.node.name}.yaml'
    record_mode = request.config.getoption('--vcrpy-mode')
    with vcr.use_cassette(str(path), record_mode=record_mode):
        yield


@pytest.fixture
async def web_client():
    async with (await init_web_client()) as web_client:
        yield web_client


@pytest.fixture
def manager(full_config, web_client):
    config = Config(**full_config).write()
    db_session = prepare_db_session(config=config)
    manager = Manager(config, db_session)
    manager.web_client = web_client
    yield manager
