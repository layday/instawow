from __future__ import annotations

from functools import lru_cache
from io import BytesIO
import json
import os
from pathlib import Path
import re
from typing import Any
from zipfile import ZipFile

import aiohttp
import aresponses
import pytest

from instawow import __version__
from instawow.common import Flavour
from instawow.config import Config
from instawow.manager import Manager, init_web_client

inf = float('inf')

FIXTURES = Path(__file__).parent / 'fixtures'


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


def load_fixture(filename: str):
    return (FIXTURES / filename).read_bytes()


def load_json_fixture(filename: str):
    return json.loads(load_fixture(filename))


@lru_cache(maxsize=None)
def make_addon_zip(*folders: str):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as file:
        for folder in folders:
            file.writestr(f'{folder}/{folder}.toc', b'')

    return buffer.getvalue()


@pytest.fixture(scope='session', autouse=True)
def iw_temp_dir(tmp_path_factory: pytest.TempPathFactory):
    temp_dir = tmp_path_factory.mktemp('temp')
    os.environ['INSTAWOW_TEMP_DIR'] = str(temp_dir)
    return temp_dir


@pytest.fixture(params=Flavour)
def iw_config_dict_no_config_dir(tmp_path: Path, request, iw_temp_dir: Path):
    addons = tmp_path / 'wow' / 'interface' / 'addons'
    addons.mkdir(parents=True)
    return {
        'global_config': {
            'temp_dir': iw_temp_dir,
        },
        'profile': '__default__',
        'addon_dir': addons,
        'game_flavour': request.param,
    }


@pytest.fixture
def iw_config_dict(tmp_path: Path, iw_config_dict_no_config_dir: dict[str, Any]):
    iw_config_dict_no_config_dir['global_config']['config_dir'] = tmp_path / 'config'
    return iw_config_dict_no_config_dir


@pytest.fixture
def iw_config(iw_config_dict: dict[str, Any]):
    return Config(**iw_config_dict).write()


@pytest.fixture
async def iw_web_client():
    async with init_web_client() as web_client:
        yield web_client


@pytest.fixture
def iw_manager(iw_config: Config, iw_web_client: aiohttp.ClientSession):
    Manager.contextualise(web_client=iw_web_client)
    manager, close_db_conn = Manager.from_config(iw_config)
    yield manager
    close_db_conn()


@pytest.fixture
@should_mock
def mock_pypi(aresponses: aresponses.ResponsesMockServer):
    aresponses.add(
        'pypi.org',
        '/pypi/instawow/json',
        'get',
        {'info': {'version': __version__}},
        repeat=inf,
    )


@pytest.fixture
@should_mock
def mock_master_catalogue(aresponses: aresponses.ResponsesMockServer):
    aresponses.add(
        'raw.githubusercontent.com',
        aresponses.ANY,
        'get',
        load_json_fixture('master-catalogue.json'),
        repeat=inf,
    )


@pytest.fixture
@should_mock
def mock_curse(aresponses: aresponses.ResponsesMockServer, mock_master_catalogue):
    aresponses.add(
        'addons-ecs.forgesvc.net',
        '/api/v2/addon',
        'post',
        load_json_fixture('curse-addon--all.json'),
        repeat=inf,
    )
    aresponses.add(
        'addons-ecs.forgesvc.net',
        '/api/v2/addon/20338/files',
        'get',
        load_json_fixture('curse-addon-files.json'),
        repeat=inf,
    )
    aresponses.add(
        'addons-ecs.forgesvc.net',
        re.compile(r'^/api/v2/addon/20338/file/(\d+)/changelog'),
        'get',
        aresponses.Response(text=load_fixture('curse-addon-changelog.txt').decode()),
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
def mock_wowi(aresponses: aresponses.ResponsesMockServer):
    aresponses.add(
        'api.mmoui.com',
        '/v3/game/WOW/filelist.json',
        'get',
        load_json_fixture('wowi-filelist.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.mmoui.com',
        re.compile(r'^/v3/game/WOW/filedetails/'),
        'get',
        load_json_fixture('wowi-filedetails.json'),
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
def mock_tukui(aresponses: aresponses.ResponsesMockServer):
    aresponses.add(
        'www.tukui.org',
        '/api.php?ui=tukui',
        'get',
        load_json_fixture('tukui-ui--tukui.json'),
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?ui=elvui',
        'get',
        load_json_fixture('tukui-ui--elvui.json'),
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?addons=all',
        'get',
        load_json_fixture('tukui-retail-addons.json'),
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?classic-addons=all',
        'get',
        load_json_fixture('tukui-classic-addons.json'),
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?classic-tbc-addons=all',
        'get',
        load_json_fixture('tukui-classic-tbc-addons.json'),
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
        re.compile(r'/classic-(?:tbc-)?addons\.php\?download=1'),
        'get',
        aresponses.Response(body=make_addon_zip('Tukui')),
        match_querystring=True,
        repeat=inf,
    )


@pytest.fixture
@should_mock
def mock_github_addons(aresponses: aresponses.ResponsesMockServer):
    aresponses.add(
        'api.github.com',
        '/repos/nebularg/PackagerTest',
        'get',
        load_json_fixture('github-repo-release-json.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/nebularg/PackagerTest/releases/latest',
        'get',
        load_json_fixture('github-release-release-json.json'),
        repeat=inf,
    )
    aresponses.add(
        'github.com',
        '/nebularg/PackagerTest/releases/download/v1.9.6/release.json',
        'get',
        load_json_fixture('github-release-release-json-release-json.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras',
        'get',
        load_json_fixture('github-repo-legacy-lib-and-nolib.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases/latest',
        'get',
        load_json_fixture('github-release-legacy-lib-and-nolib.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases?per_page=1',
        'get',
        [load_json_fixture('github-release-legacy-lib-and-nolib.json')],
        match_querystring=True,
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases/tags/2.1.0',
        'get',
        load_json_fixture('github-release-legacy-lib-and-nolib-older-version.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/p3lim-wow/Molinari',
        'get',
        load_json_fixture('github-repo-legacy-retail-and-classic.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/p3lim-wow/Molinari/releases/latest',
        'get',
        load_json_fixture('github-release-legacy-retail-and-classic.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiBags',
        'get',
        load_json_fixture('github-repo-no-releases.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiBags/releases/latest',
        'get',
        aresponses.Response(body=b'', status=404),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19',
        'get',
        load_json_fixture('github-release-no-assets.json'),
        repeat=inf,
    )
    aresponses.add(
        'api.github.com',
        '/repos/layday/foobar',
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
def mock_github_oauth(aresponses: aresponses.ResponsesMockServer):
    aresponses.add(
        'github.com',
        '/login/device/code',
        'post',
        load_json_fixture('github-oauth-login-device-code.json'),
        repeat=inf,
    )
    aresponses.add(
        'github.com',
        '/login/oauth/access_token',
        'post',
        load_json_fixture('github-oauth-login-access-token.json'),
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
    mock_github_addons,
    mock_github_oauth,
):
    pass
