from __future__ import annotations

from pathlib import Path
from typing import Any

import aiohttp
import aiohttp.web
import pytest
from aresponses import ResponsesMockServer
from aresponses.errors import NoRouteFoundError
from yarl import URL

import instawow._logging
import instawow.config
import instawow.http
import instawow.shared_ctx
from instawow.shared_ctx import ConfigBoundCtx
from instawow.wow_installations import _DELECTABLE_DIR_NAMES, Flavour

from .fixtures.http import ROUTES


def pytest_addoption(parser: pytest.Parser):
    parser.addoption('--iw-no-mock-http', action='store_true')


@pytest.fixture(autouse=True)
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def caplog(caplog: pytest.LogCaptureFixture):
    handler_id = instawow._logging.logger.add(
        caplog.handler,
        format='{message}',
        level=0,
        filter=lambda record: record['level'].no >= caplog.handler.level,
        enqueue=False,  # Set to 'True' if your test is spawning child processes.
    )
    yield caplog
    instawow._logging.logger.remove(handler_id)


class _StrictResponsesMockServer(ResponsesMockServer):
    async def _find_response(self, request: aiohttp.web.Request):
        response = await super()._find_response(request)
        if response == (None, None):
            raise NoRouteFoundError(f'No match found for <{request.method} {request.url}>')
        return response


@pytest.fixture
async def iw_aresponses():
    async with _StrictResponsesMockServer() as server:
        yield server


@pytest.fixture(params=['foo'])
def iw_global_config_values(request: pytest.FixtureRequest, tmp_path: Path):
    return {
        'config_dir': tmp_path / '__config__' / 'config',
        'temp_dir': tmp_path / '__config__' / 'temp',
        'state_dir': tmp_path / '__config__' / 'state',
        'access_tokens': {
            'cfcore': request.param,
            'github': None,
            'wago': None,
            'wago_addons': request.param,
        },
    }


@pytest.fixture(params=[Flavour.Retail])
def iw_profile_config_values(request: pytest.FixtureRequest, tmp_path: Path):
    installation_dir = (
        tmp_path
        / 'wow'
        / next(
            (k for k, v in _DELECTABLE_DIR_NAMES.items() if v['flavour'] is request.param),
            '_unknown_',
        )
    )
    addon_dir = installation_dir / 'interface' / 'addons'
    addon_dir.mkdir(parents=True)
    return {
        'profile': '__default__',
        'addon_dir': addon_dir,
        'game_flavour': request.param,
        '_installation_dir': installation_dir,
    }


@pytest.fixture
def iw_global_config(iw_global_config_values: dict[str, Any]):
    return instawow.config.GlobalConfig.from_values(iw_global_config_values).write()


@pytest.fixture
def iw_profile_config(
    iw_profile_config_values: dict[str, Any], iw_global_config: instawow.config.GlobalConfig
):
    return instawow.config.ProfileConfig.from_values(
        {'global_config': iw_global_config, **iw_profile_config_values}
    ).write()


@pytest.fixture(autouse=True)
def _iw_global_config_defaults(
    monkeypatch: pytest.MonkeyPatch,
    iw_global_config_values: dict[str, Any],
):
    for key in 'config_dir', 'temp_dir', 'state_dir':
        monkeypatch.setenv(f'INSTAWOW_{key.upper()}', str(iw_global_config_values[key]))


@pytest.fixture
async def iw_web_client(iw_global_config: instawow.config.GlobalConfig):
    async with instawow.http.init_web_client(iw_global_config.http_cache_dir) as web_client:
        yield web_client


@pytest.fixture
async def _iw_web_client_ctx(iw_web_client: instawow.http.ClientSession):
    instawow.shared_ctx.web_client_var.set(iw_web_client)


@pytest.fixture
def iw_config_ctx(iw_profile_config: instawow.config.ProfileConfig):
    with ConfigBoundCtx(iw_profile_config) as config_ctx:
        yield config_ctx


@pytest.fixture(autouse=True, params=['all'])
async def _iw_mock_aiohttp_requests(
    request: pytest.FixtureRequest, iw_aresponses: _StrictResponsesMockServer
):
    if request.config.getoption('--iw-no-mock-http') or any(
        m.name == 'iw_no_mock_http' for m in request.node.iter_markers()
    ):
        await iw_aresponses.__aexit__(*((None,) * 3))
        return

    if request.param == 'all':
        routes = ROUTES.values()
    else:
        urls = set(map(URL, request.param))
        if not urls.issubset(ROUTES.keys()):
            raise ValueError('Supplied routes must be subset of all routes')

        routes = (ROUTES[k] for k in ROUTES.keys() & urls)

    for route in routes:
        iw_aresponses.add(**route.to_aresponses_add_args())
