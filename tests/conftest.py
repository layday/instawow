from functools import lru_cache
from io import BytesIO
import json
import os
from pathlib import Path
import re
from zipfile import ZipFile

import pytest

from instawow.config import Config, Flavour
from instawow.manager import Manager, init_web_client
from instawow.utils import get_version

inf = float('inf')


def pytest_addoption(parser):
    parser.addoption('--iw-no-mock', action='store_true')


def should_mock(fn):
    import inspect
    import warnings

    def wrapper(request):
        if request.config.getoption('--iw-no-mock'):
            warnings.warn('not mocking')
            return None
        elif any(m.name == 'iw_no_mock' for m in request.node.iter_markers()):
            return None
        elif request.module.__name__ == 'test_json_rpc_api':
            # aresponses conflicts with aiohttp's own test server
            return None

        args = (request.getfixturevalue(p) for p in inspect.signature(fn).parameters)
        return fn(*args)

    return wrapper


@lru_cache(maxsize=None)
def read_json_fixture(filename):
    return json.loads((Path(__file__).parent / 'fixtures' / filename).read_bytes())


@lru_cache(maxsize=None)
def make_addon_zip(*folders):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as file:
        for folder in folders:
            file.writestr(f'{folder}/{folder}.toc', b'')

    return buffer.getvalue()


@pytest.fixture(scope='session', autouse=True)
def iw_temp_dir(tmp_path_factory):
    temp_dir = os.environ['INSTAWOW_TEMP_DIR'] = str(tmp_path_factory.mktemp('temp'))
    yield temp_dir


@pytest.fixture(params=Flavour)
def iw_partial_config(tmp_path, request, iw_temp_dir):
    addons = tmp_path / 'wow' / 'interface' / 'addons'
    addons.mkdir(parents=True)
    return {'addon_dir': addons, 'temp_dir': iw_temp_dir, 'game_flavour': request.param}


@pytest.fixture
def iw_full_config(tmp_path, iw_partial_config):
    return {**iw_partial_config, 'config_dir': tmp_path / 'config'}


@pytest.fixture
def iw_config(iw_full_config):
    yield Config(**iw_full_config).write()


@pytest.fixture
async def iw_web_client():
    async with init_web_client() as web_client:
        yield web_client


@pytest.fixture
def iw_manager(iw_config, iw_web_client):
    manager = Manager.from_config(iw_config)
    manager.contextualise(web_client=iw_web_client)
    yield manager


@pytest.fixture
@should_mock
def mock_pypi(aresponses):
    aresponses.add(
        'pypi.org',
        '/pypi/instawow/json',
        'get',
        {'info': {'version': get_version()}},
        repeat=inf,
    )


@pytest.fixture
@should_mock
def mock_master_catalogue(aresponses):
    aresponses.add(
        'raw.githubusercontent.com',
        aresponses.ANY,
        'get',
        read_json_fixture('master-catalogue.json'),
        repeat=inf,
    )


@pytest.fixture
@should_mock
def mock_curse(aresponses, mock_master_catalogue):
    aresponses.add(
        'addons-ecs.forgesvc.net',
        '/api/v2/addon',
        'post',
        read_json_fixture('curse-addon--all.json'),
        repeat=inf,
    )
    aresponses.add(
        'addons-ecs.forgesvc.net',
        '/api/v2/addon/20338/files',
        'get',
        read_json_fixture('curse-addon-files.json'),
        repeat=inf,
    )
    aresponses.add(
        'edge.forgecdn.net',
        aresponses.ANY,
        'get',
        aresponses.Response(body=make_addon_zip('Molinari')),
        repeat=inf,
    )


@pytest.fixture
@should_mock
def mock_wowi(aresponses, mock_master_catalogue):
    aresponses.add(
        'api.mmoui.com',
        '/v3/game/WOW/filelist.json',
        'get',
        read_json_fixture('wowi-filelist.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.mmoui.com',
        re.compile(r'^/v3/game/WOW/filedetails/'),
        'get',
        read_json_fixture('wowi-filedetails.json'),
        repeat=inf,
    )
    aresponses.add(
        'cdn.wowinterface.com',
        aresponses.ANY,
        'get',
        aresponses.Response(body=make_addon_zip('Molinari')),
        repeat=inf,
    )


@pytest.fixture
@should_mock
def mock_tukui(aresponses, mock_master_catalogue):
    aresponses.add(
        'www.tukui.org',
        '/api.php?ui=tukui',
        'get',
        read_json_fixture('tukui-ui--tukui.json'),
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?ui=elvui',
        'get',
        read_json_fixture('tukui-ui--elvui.json'),
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?addons=all',
        'get',
        read_json_fixture('tukui-retail-addons.json'),
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?classic-addons=all',
        'get',
        read_json_fixture('tukui-classic-addons.json'),
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php',
        'get',
        '',
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        re.compile(r'^/downloads/tukui'),
        'get',
        aresponses.Response(body=make_addon_zip('Tukui')),
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/addons.php?download=1',
        'get',
        aresponses.Response(body=make_addon_zip('ElvUI_MerathilisUI')),
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/classic-addons.php?download=1',
        'get',
        aresponses.Response(body=make_addon_zip('Tukui')),
        match_querystring=True,
        repeat=inf,
    )


@pytest.fixture
@should_mock
def mock_github(aresponses):
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras',
        'get',
        read_json_fixture('github-repo-lib-and-nolib.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases/latest',
        'get',
        read_json_fixture('github-release-lib-and-nolib.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases?per_page=1',
        'get',
        [read_json_fixture('github-release-lib-and-nolib.json')],
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases/tags/2.1.0',
        'get',
        read_json_fixture('github-release-lib-and-nolib-older-version.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/WeakAuras/WeakAuras2',
        'get',
        read_json_fixture('github-repo-retail-and-classic.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/WeakAuras/WeakAuras2/releases/latest',
        'get',
        read_json_fixture('github-release-retail-and-classic.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/p3lim-wow/Molinari',
        'get',
        read_json_fixture('github-repo-no-releases.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/p3lim-wow/Molinari/releases/latest',
        'get',
        aresponses.Response(body=b'', status=404),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19',
        'get',
        read_json_fixture('github-release-no-assets.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/layday/foo-bar',
        'get',
        aresponses.Response(body=b'', status=404),
        repeat=inf,
    )
    aresponses.add(
        'github.com',
        re.compile(r'^(/[^/]*){2}/releases/download'),
        'get',
        aresponses.Response(body=make_addon_zip('Foo')),
        repeat=inf,
    )


@pytest.fixture
@should_mock
def mock_townlong_yak(aresponses):
    aresponses.add(
        'hub.wowup.io',
        '/addons/author/foxlit',
        'get',
        read_json_fixture('wowup-hub-townlong-yak.json'),
        repeat=inf,
    )
    aresponses.add(
        'www.townlong-yak.com',
        re.compile(r'^/addons/ul/[0-9a-z]{41}/install\.zip'),
        'get',
        aresponses.Response(body=make_addon_zip('Foo')),
        repeat=inf,
    )


@pytest.fixture(autouse=True)
@should_mock
def mock_all(
    mock_pypi,
    mock_master_catalogue,
    mock_curse,
    mock_wowi,
    mock_tukui,
    mock_github,
    mock_townlong_yak,
):
    pass
