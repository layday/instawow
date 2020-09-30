from functools import lru_cache
import json
import os
from pathlib import Path
import re

import pytest

from instawow.config import Config
from instawow.manager import Manager
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
    return json.loads((Path(__file__).parent / 'fixtures' / filename).read_bytes())


@lru_cache(maxsize=None)
def make_zip(name):
    from io import BytesIO
    from zipfile import ZipFile

    buffer = BytesIO()
    with ZipFile(buffer, 'w') as file:
        file.writestr(f'{name}/{name}.toc', b'')
    return buffer.getvalue()


@pytest.fixture(scope='session', autouse=True)
def temp_dir(tmp_path_factory):
    temp_dir = os.environ['INSTAWOW_TEMP_DIR'] = str(tmp_path_factory.mktemp('temp'))
    yield temp_dir


@pytest.fixture(params=['retail', 'classic'])
def partial_config(tmp_path, request, temp_dir):
    addons = tmp_path / 'wow' / 'interface' / 'addons'
    addons.mkdir(parents=True)
    return {'addon_dir': addons, 'temp_dir': temp_dir, 'game_flavour': request.param}


@pytest.fixture
def full_config(tmp_path, partial_config):
    return {**partial_config, 'config_dir': tmp_path / 'config'}


@pytest.fixture
def manager(full_config):
    yield Manager.from_config(Config(**full_config).write())


@pytest.fixture
@should_mock
def mock_pypi(aresponses):
    aresponses.add(
        'pypi.org',
        '/pypi/instawow/json',
        'get',
        {'info': {'version': get_version()}},
        repeat=float('inf'),
    )


@pytest.fixture
@should_mock
def mock_master_catalogue(aresponses):
    aresponses.add(
        'raw.githubusercontent.com',
        aresponses.ANY,
        'get',
        read_fixture('master-catalogue.json'),
        repeat=float('inf'),
    )


@pytest.fixture
@should_mock
def mock_curse(aresponses, mock_master_catalogue):
    aresponses.add(
        'addons-ecs.forgesvc.net',
        '/api/v2/addon',
        'post',
        read_fixture('curse-addon--all.json'),
        repeat=float('inf'),
    )
    aresponses.add(
        'addons-ecs.forgesvc.net',
        '/api/v2/addon/20338/files',
        'get',
        read_fixture('curse-addon-files.json'),
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
def mock_wowi(aresponses, mock_master_catalogue):
    aresponses.add(
        'api.mmoui.com',
        '/v3/game/WOW/filelist.json',
        'get',
        read_fixture('wowi-filelist.json'),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.mmoui.com',
        re.compile(r'^/v3/game/WOW/filedetails/'),
        'get',
        read_fixture('wowi-filedetails.json'),
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
def mock_tukui(aresponses, mock_master_catalogue):
    aresponses.add(
        'www.tukui.org',
        '/api.php?ui=tukui',
        'get',
        read_fixture('tukui-ui--tukui.json'),
        match_querystring=True,
        repeat=float('inf'),
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?addon=1',
        'get',
        read_fixture('tukui-addon.json'),
        match_querystring=True,
        repeat=float('inf'),
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php?classic-addon=1',
        'get',
        read_fixture('tukui-classic-addon.json'),
        match_querystring=True,
        repeat=float('inf'),
    )
    aresponses.add(
        'www.tukui.org',
        '/api.php',
        'get',
        '',
        repeat=float('inf'),
    )
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


@pytest.fixture
@should_mock
def mock_github(aresponses, mock_master_catalogue):
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras',
        'get',
        read_fixture('github-repo-lib-and-nolib.json'),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases/latest',
        'get',
        read_fixture('github-release-lib-and-nolib.json'),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases/tags/2.1.0',
        'get',
        read_fixture('github-release-lib-and-nolib-older-version.json'),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.github.com',
        '/repos/WeakAuras/WeakAuras2',
        'get',
        read_fixture('github-repo-retail-and-classic.json'),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.github.com',
        '/repos/WeakAuras/WeakAuras2/releases/latest',
        'get',
        read_fixture('github-release-retail-and-classic.json'),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.github.com',
        '/repos/p3lim-wow/Molinari',
        'get',
        read_fixture('github-repo-no-releases.json'),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.github.com',
        '/repos/p3lim-wow/Molinari/releases/latest',
        'get',
        aresponses.Response(body=b'', status=404),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.github.com',
        '/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19',
        'get',
        read_fixture('github-release-no-assets.json'),
        repeat=float('inf'),
    )
    aresponses.add(
        'api.github.com',
        '/repos/layday/foo-bar',
        'get',
        aresponses.Response(body=b'', status=404),
        repeat=float('inf'),
    )
    aresponses.add(
        'github.com',
        re.compile(r'^(/[^/]*){2}/releases/download'),
        'get',
        aresponses.Response(body=make_zip('Foo')),
        repeat=float('inf'),
    )


@pytest.fixture
def mock_all(
    mock_pypi,
    mock_master_catalogue,
    mock_curse,
    mock_wowi,
    mock_tukui,
    mock_github,
):
    pass
