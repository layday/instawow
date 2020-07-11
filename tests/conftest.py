from functools import lru_cache, partial
from pathlib import Path
import re

import pytest

from instawow.config import Config
from instawow.manager import Manager, init_web_client, prepare_db_session
from instawow.utils import get_version


def pytest_addoption(parser):
    parser.addoption('--instawow-no-mock', action='store_true')


def should_mock(fn):
    import inspect
    import warnings

    def wrapper(request):
        if request.config.getoption('--instawow-no-mock'):
            warnings.warn('not mocking')
            return None

        args = (request.getfixturevalue(p) for p in inspect.signature(fn).parameters)
        return fn(*args)

    return wrapper


@lru_cache(maxsize=None)
def read_fixture(filename):
    return (Path(__file__).parent / 'fixtures' / filename).read_bytes()


@lru_cache(maxsize=None)
def make_zip(name):
    from io import BytesIO
    from zipfile import ZipFile

    buffer = BytesIO()
    with ZipFile(buffer, 'w') as file:
        file.writestr(f'{name}/{name}.toc', b'')
    return buffer.getvalue()


@pytest.fixture(scope='session')
def temp_dir(tmp_path_factory):
    yield tmp_path_factory.mktemp('temp')


@pytest.fixture(params=['retail', 'classic'])
def partial_config(tmp_path, request, temp_dir):
    addons = tmp_path / 'wow' / 'interface' / 'addons'
    addons.mkdir(parents=True)
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


@pytest.fixture
def JsonResponse(aresponses):
    return partial(aresponses.Response, headers={'Content-Type': 'application/json'})


@pytest.fixture
def mock_pypi(aresponses, JsonResponse):
    aresponses.add(
        'pypi.org',
        '/pypi/instawow/json',
        'get',
        JsonResponse(body=f'{{"info": {{"version": "{get_version()}"}}}}'),
        repeat=float('inf'),
    )


@pytest.fixture
@should_mock
def mock_master_catalogue(aresponses, JsonResponse):
    aresponses.add(
        'raw.githubusercontent.com',
        aresponses.ANY,
        'get',
        JsonResponse(body=read_fixture('master-catalogue.json')),
        repeat=float('inf'),
    )


@pytest.fixture
@should_mock
def mock_curse(aresponses, JsonResponse, mock_master_catalogue):
    aresponses.add(
        'addons-ecs.forgesvc.net',
        '/api/v2/addon',
        'post',
        JsonResponse(body=read_fixture('curse-post-addon_all.json')),
        repeat=float('inf'),
    )
    aresponses.add(
        'addons-ecs.forgesvc.net',
        '/api/v2/addon/20338/files',
        'get',
        JsonResponse(body=read_fixture('curse-get-addon-files.json')),
        repeat=float('inf'),
    )
    aresponses.add(
        'edge.forgecdn.net',
        aresponses.ANY,
        'get',
        aresponses.Response(body=make_zip('Molinari')),
        repeat=float('inf'),
    )


@pytest.fixture
@should_mock
def mock_wowi(aresponses, JsonResponse, mock_master_catalogue):
    aresponses.add(
        'api.mmoui.com',
        '/v3/game/WOW/filelist.json',
        'get',
        JsonResponse(body=read_fixture('wowi-get-filelist.json')),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.mmoui.com',
        re.compile(r'^/v3/game/WOW/filedetails/'),
        'get',
        JsonResponse(body=read_fixture('wowi-get-filedetails.json')),
        repeat=float('inf'),
    )
    aresponses.add(
        'cdn.wowinterface.com',
        aresponses.ANY,
        'get',
        aresponses.Response(body=make_zip('Molinari')),
        repeat=float('inf'),
    )


@pytest.fixture
@should_mock
def mock_tukui(aresponses, JsonResponse, mock_master_catalogue):
    aresponses.add(
        'www.tukui.org',
        '/api.php?ui=tukui',
        'get',
        JsonResponse(body=read_fixture('tukui-get-ui_tukui.json')),
        match_querystring=True,
        repeat=float('inf'),
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?addon=1',
        'get',
        JsonResponse(body=read_fixture('tukui-get-addon.json')),
        match_querystring=True,
        repeat=float('inf'),
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?classic-addon=1',
        'get',
        JsonResponse(body=read_fixture('tukui-get-classic-addon.json')),
        match_querystring=True,
        repeat=float('inf'),
    )
    aresponses.add('www.tukui.org', '/api.php', 'get', '', repeat=float('inf'))
    aresponses.add(
        'www.tukui.org',
        re.compile(r'^/downloads/tukui'),
        'get',
        aresponses.Response(body=make_zip('Tukui')),
        repeat=float('inf'),
    )
    aresponses.add(
        'www.tukui.org',
        '/addons.php?download=1',
        'get',
        aresponses.Response(body=make_zip('ElvUI_MerathilisUI')),
        match_querystring=True,
        repeat=float('inf'),
    )
    aresponses.add(
        'www.tukui.org',
        '/classic-addons.php?download=1',
        'get',
        aresponses.Response(body=make_zip('Tukui')),
        match_querystring=True,
        repeat=float('inf'),
    )


@pytest.fixture(autouse=True)
def mock_all(mock_pypi, mock_curse, mock_wowi, mock_tukui):
    pass
