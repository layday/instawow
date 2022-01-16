from __future__ import annotations

from collections.abc import Callable as C
from functools import partial
import json
from typing import Any

from aiohttp import ClientWebSocketResponse, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer
import pytest
from yarl import URL

from instawow.config import Config

try:
    from instawow_gui import json_rpc_server
except ImportError:
    pytestmark = pytest.mark.skip(reason='instawow_gui is not available')
else:
    pytestmark = pytest.mark.iw_no_mock_http


dumps = partial(json.dumps, default=str)


@pytest.fixture
async def ws_client(
    monkeypatch: pytest.MonkeyPatch,
    iw_global_config_values: dict[str, Any],
):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_global_config_values['config_dir']))
    app = await json_rpc_server.create_app()
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
    iw_config_values: dict[str, Any],
    ws: ClientWebSocketResponse,
):
    config_values = {**iw_config_values, 'profile': request.node.name}
    rpc_request = {
        'jsonrpc': '2.0',
        'method': 'config/write_profile',
        'params': {**config_values, 'infer_game_flavour': False},
        'id': request.node.name,
    }
    await ws.send_json(rpc_request, dumps=dumps)
    rpc_response = await ws.receive_json()
    assert rpc_response['id'] == request.node.name
    assert Config.parse_obj(rpc_response['result']) == Config.parse_obj(
        {'global_config': iw_global_config_values, **config_values}
    )


async def test_write_config_with_invalid_params(
    request: pytest.FixtureRequest,
    iw_config_values: dict[str, Any],
    ws: ClientWebSocketResponse,
):
    rpc_request = {
        'jsonrpc': '2.0',
        'method': 'config/write_profile',
        'params': {
            **iw_config_values,
            'game_flavour': 'strawberry',
            'infer_game_flavour': False,
        },
        'id': request.node.name,
    }
    await ws.send_json(rpc_request, dumps=dumps)
    rpc_response = await ws.receive_json()
    assert rpc_response['id'] == request.node.name
    assert rpc_response['error']
    assert rpc_response['error']['code'] == -32602
    assert rpc_response['error']['message'] == 'Invalid method parameter(s).'
    assert rpc_response['error']['data'] == [
        {
            'loc': ['game_flavour'],
            'msg': "value is not a valid enumeration member; permitted: 'retail', 'vanilla_classic', 'classic'",
            'type': 'type_error.enum',
            'ctx': {'enum_values': ['retail', 'vanilla_classic', 'classic']},
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
    assert rpc_response['error'] and rpc_response['error']['code'] == -32602


@pytest.mark.xfail
async def test_install_with_uninitialised_profile(
    request: pytest.FixtureRequest,
    ws: ClientWebSocketResponse,
):
    rpc_request = {
        'jsonrpc': '2.0',
        'method': 'install',
        'params': {
            'profile': request.node.name,
            'defns': [{'source': 'curse', 'name': 'molinari'}],
            'replace': False,
        },
        'id': request.node.name,
    }
    await ws.send_json(rpc_request, dumps=dumps)
    rpc_response = await ws.receive_json()
    assert rpc_response['error'] and rpc_response['error']['code'] == -32001
