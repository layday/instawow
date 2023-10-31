from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import aiohttp
import aiohttp.web
import pytest
from aresponses import ResponsesMockServer
from aresponses.errors import NoRouteFoundError
from loguru import logger

from instawow.common import Flavour
from instawow.config import Config, GlobalConfig
from instawow.http import init_web_client
from instawow.manager_ctx import ManagerCtx, contextualise
from instawow.pkg_management import PkgManager

from .fixtures.http import ROUTES


def pytest_addoption(parser: pytest.Parser):
    parser.addoption('--iw-no-mock-http', action='store_true')


def should_mock(fn: Callable[..., object]):
    import inspect

    def wrapper(request: pytest.FixtureRequest):
        if request.config.getoption('--iw-no-mock-http'):
            return None
        elif any(m.name == 'iw_no_mock_http' for m in request.node.iter_markers()):
            return None

        args = (request.getfixturevalue(p) for p in inspect.signature(fn).parameters)
        return fn(*args)

    return wrapper


@pytest.fixture
def caplog(caplog: pytest.LogCaptureFixture):
    handler_id = logger.add(
        caplog.handler,
        format='{message}',
        level=0,
        filter=lambda record: record['level'].no >= caplog.handler.level,
        enqueue=False,  # Set to 'True' if your test is spawning child processes.
    )
    yield caplog
    logger.remove(handler_id)


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
def iw_config_values(request: pytest.FixtureRequest, tmp_path: Path):
    addons = tmp_path / 'wow' / 'interface' / 'addons'
    addons.mkdir(parents=True)
    return {'profile': '__default__', 'addon_dir': addons, 'game_flavour': request.param}


@pytest.fixture
def iw_config(iw_config_values: dict[str, Any], iw_global_config_values: dict[str, Any]):
    global_config = GlobalConfig.from_values(iw_global_config_values).write()
    return Config.from_values({'global_config': global_config, **iw_config_values}).write()


@pytest.fixture(autouse=True)
def _iw_global_config_defaults(
    monkeypatch: pytest.MonkeyPatch,
    iw_global_config_values: dict[str, Any],
):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_global_config_values['config_dir']))
    monkeypatch.setenv('INSTAWOW_TEMP_DIR', str(iw_global_config_values['temp_dir']))
    monkeypatch.setenv('INSTAWOW_STATE_DIR', str(iw_global_config_values['state_dir']))


@pytest.fixture
async def iw_web_client(iw_config: Config):
    async with init_web_client(iw_config.global_config.cache_dir) as web_client:
        yield web_client


@pytest.fixture
def iw_manager_ctx(iw_config: Config, iw_web_client: aiohttp.ClientSession):
    contextualise(web_client=iw_web_client)
    return ManagerCtx.from_config(iw_config)


@pytest.fixture
def iw_manager(iw_manager_ctx: ManagerCtx):
    return PkgManager(iw_manager_ctx)


@pytest.fixture(autouse=True, params=['all'])
@should_mock
def _iw_mock_aiohttp_requests(
    request: pytest.FixtureRequest, iw_aresponses: _StrictResponsesMockServer
):
    if request.param == 'all':
        routes = ROUTES.values()
    else:
        if not request.param.issubset(ROUTES.keys()):
            raise ValueError('Supplied routes must be subset of all routes')

        routes = (ROUTES[k] for k in ROUTES.keys() & request.param)

    for route in routes:
        iw_aresponses.add(**route.to_aresponses_add_args())
