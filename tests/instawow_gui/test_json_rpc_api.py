from __future__ import annotations

import json
from collections.abc import Callable as C
from functools import partial
from typing import Any

import pytest
from aiohttp import ClientWebSocketResponse, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer
from yarl import URL

from instawow.config import GlobalConfig, ProfileConfig, config_converter

try:
    from instawow_gui import _json_rpc_server as json_rpc_server
except ModuleNotFoundError:
    pytest.skip(reason='instawow_gui is not available', allow_module_level=True)


dumps = partial(json.dumps, default=str)


@pytest.fixture
def _iw_mock_aiohttp_requests():
    pass


@pytest.fixture
async def ws_client(iw_profile_config: object):
    app = await json_rpc_server.create_web_app()
    server = TestServer(app)
    async with TestClient(server) as client:
        yield client


@pytest.fixture
async def ws(ws_client: TestClient):
    async with ws_client.ws_connect('/api', origin=str(ws_client.make_url(''))) as ws:
        yield ws


async def test_no_origin_api_request_rejected(ws_client: TestClient):
    with pytest.raises(WSServerHandshakeError):
        async with ws_client.ws_connect('/api'):
            pass


@pytest.mark.parametrize(
    'transform',
    [
        lambda u: u.with_scheme('ftp'),
        lambda u: u.with_host('example.com'),
        lambda u: u.with_port(21),
    ],
)
async def test_disparate_origin_api_request_rejected(
    ws_client: TestClient,
    transform: C[[URL], URL],
):
    with pytest.raises(WSServerHandshakeError):
        async with ws_client.ws_connect('/api', origin=str(transform(ws_client.make_url('')))):
            pass


async def test_write_config(
    request: pytest.FixtureRequest,
    iw_global_config_values: dict[str, Any],
    iw_profile_config_values: dict[str, Any],
    ws: ClientWebSocketResponse,
):
    global_config = config_converter.structure(iw_global_config_values, GlobalConfig).write()
    config_values = {**iw_profile_config_values, 'profile': request.node.name}
    config_values.pop('_installation_dir')
    rpc_request = {
        'jsonrpc': '2.0',
        'method': 'config/write_profile',
        'params': {**config_values, 'infer_track': False},
        'id': request.node.name,
    }
    await ws.send_json(rpc_request, dumps=dumps)
    rpc_response = await ws.receive_json()
    assert rpc_response['id'] == request.node.name
    assert config_converter.structure(
        rpc_response['result'], ProfileConfig
    ) == config_converter.structure(
        {'global_config': global_config, **config_values}, ProfileConfig
    )


async def test_write_config_with_invalid_params(
    request: pytest.FixtureRequest,
    iw_profile_config_values: dict[str, Any],
    ws: ClientWebSocketResponse,
):
    config_values = {
        **iw_profile_config_values,
        'track': 'strawberry',
        'infer_track': False,
    }
    config_values.pop('_installation_dir')
    rpc_request = {
        'jsonrpc': '2.0',
        'method': 'config/write_profile',
        'params': config_values,
        'id': request.node.name,
    }
    await ws.send_json(rpc_request, dumps=dumps)
    rpc_response = await ws.receive_json()
    assert rpc_response['id'] == request.node.name
    assert rpc_response['error']
    assert rpc_response['error']['code'] == -32602
    assert rpc_response['error']['message'] == 'invalid params'
    assert rpc_response['error']['data'] == [
        {
            'path': ['params', 'track'],
            'message': 'ValueError("\'strawberry\' is not a valid Track")',
        }
    ]


async def test_install_with_invalid_params(
    request: pytest.FixtureRequest,
    ws: ClientWebSocketResponse,
):
    rpc_request = {
        'jsonrpc': '2.0',
        'method': 'install',
        'params': {},
        'id': request.node.name,
    }
    await ws.send_json(rpc_request, dumps=dumps)
    rpc_response = await ws.receive_json()
    assert rpc_response['error']
    assert rpc_response['error']['code'] == -32602
