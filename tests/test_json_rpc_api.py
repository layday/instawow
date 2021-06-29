from functools import partial
import json

from aiohttp.test_utils import TestClient, TestServer
import pytest

from instawow.config import Config

try:
    from instawow_gui import json_rpc_server
except ImportError:
    pytestmark = pytest.mark.skip(reason='instawow_gui is not available')


dumps = partial(json.dumps, default=str)


@pytest.fixture
async def ws(iw_config_dict, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_config_dict['config_dir']))
    app = await json_rpc_server.create_app()
    server = TestServer(app)
    async with TestClient(server) as client, client.ws_connect('/api') as ws:
        yield ws


@pytest.mark.asyncio
async def test_write_config(request, iw_config_dict, ws):
    config_values = {**iw_config_dict, 'profile': request.node.name}
    rpc_request = {
        'jsonrpc': '2.0',
        'method': 'config/write',
        'params': {'values': config_values, 'infer_game_flavour': False},
        'id': request.node.name,
    }
    await ws.send_json(rpc_request, dumps=dumps)
    rpc_response = await ws.receive_json()
    assert rpc_response['id'] == request.node.name
    assert Config.parse_obj(rpc_response['result']) == Config.parse_obj(config_values)


@pytest.mark.asyncio
async def test_write_config_with_invalid_params(request, iw_config_dict, ws):
    rpc_request = {
        'jsonrpc': '2.0',
        'method': 'config/write',
        'params': {
            'values': {**iw_config_dict, 'game_flavour': 'strawberry'},
            'infer_game_flavour': False,
        },
        'id': request.node.name,
    }
    await ws.send_json(rpc_request, dumps=dumps)
    rpc_response = await ws.receive_json()
    assert rpc_response['id'] == request.node.name
    assert rpc_response['error']
    assert rpc_response['error']['code'] == -32001
    assert rpc_response['error']['message'] == 'invalid configuration parameters'
    assert rpc_response['error']['data'] == [
        {
            'loc': ['game_flavour'],
            'msg': "value is not a valid enumeration member; permitted: 'retail', 'vanilla_classic', 'classic'",
            'type': 'type_error.enum',
            'ctx': {'enum_values': ['retail', 'vanilla_classic', 'classic']},
        }
    ]


@pytest.mark.asyncio
async def test_install_with_invalid_params(request, ws):
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
@pytest.mark.asyncio
async def test_install_with_uninitialised_profile(request, ws):
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
