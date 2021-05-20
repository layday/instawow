from aiohttp.test_utils import TestClient, TestServer
from aiohttp_rpc import JsonRpcRequest as Request, JsonRpcResponse as Response
import pytest

from instawow.config import Config
from instawow.json_rpc_server import _serialise_response, create_app


@pytest.fixture
async def ws(iw_config_dict, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(iw_config_dict['config_dir']))
    app, endpoint = await create_app()
    server = TestServer(app)
    async with TestClient(server) as client, client.ws_connect(endpoint) as ws:
        yield ws


@pytest.mark.asyncio
async def test_write_config(request, iw_config_dict, ws):
    config_values = {**iw_config_dict, 'profile': request.node.name}
    rpc_request = Request(
        method='config/write',
        params={'values': config_values, 'infer_game_flavour': False},
        msg_id=request.node.name,
    )
    await ws.send_str(_serialise_response(rpc_request.to_dict()))
    rpc_response = Response.from_dict(await ws.receive_json())
    assert rpc_response.msg_id == request.node.name
    assert Config.parse_obj(rpc_response.result) == Config.parse_obj(config_values)


@pytest.mark.asyncio
async def test_write_config_with_invalid_params(request, iw_config_dict, ws):
    rpc_request = Request(
        method='config/write',
        params={
            'values': {**iw_config_dict, 'game_flavour': 'strawberry'},
            'infer_game_flavour': False,
        },
        msg_id=request.node.name,
    )
    await ws.send_str(_serialise_response(rpc_request.to_dict()))
    rpc_response = Response.from_dict(await ws.receive_json())
    assert rpc_response.msg_id == request.node.name
    assert rpc_response.error
    error = rpc_response.error
    assert error.code == -32001
    assert rpc_response.error.message == 'invalid configuration parameters'
    assert rpc_response.error.data == [
        {
            'loc': ['game_flavour'],
            'msg': "value is not a valid enumeration member; permitted: 'retail', 'classic', 'vanilla_classic'",
            'type': 'type_error.enum',
            'ctx': {'enum_values': ['retail', 'classic', 'vanilla_classic']},
        }
    ]


@pytest.mark.asyncio
async def test_install_with_invalid_params(request, ws):
    rpc_request = Request(
        method='install',
        params={},
        msg_id=request.node.name,
    )
    await ws.send_str(_serialise_response(rpc_request.to_dict()))
    rpc_response = Response.from_dict(await ws.receive_json())
    assert rpc_response.error and rpc_response.error.code == -32602


@pytest.mark.xfail
@pytest.mark.asyncio
async def test_install_with_uninitialised_profile(request, ws):
    rpc_request = Request(
        method='install',
        params={
            'profile': request.node.name,
            'defns': [{'source': 'curse', 'name': 'molinari'}],
            'replace': False,
        },
        msg_id=request.node.name,
    )
    await ws.send_str(_serialise_response(rpc_request.to_dict()))
    rpc_response = Response.from_dict(await ws.receive_json())
    assert rpc_response.error and rpc_response.error.code == -32001
