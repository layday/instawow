from aiohttp.test_utils import TestClient, TestServer
import pytest

from instawow.config import Config
from instawow.json_rpc_server import ErrorResponse, Request, SuccessResponse, create_app


@pytest.fixture
async def ws(full_config, monkeypatch):
    monkeypatch.setenv('INSTAWOW_CONFIG_DIR', str(full_config['config_dir']))
    app = await create_app()
    server = TestServer(app)

    async with TestClient(server) as client:
        async with client.ws_connect('/v0') as ws:
            yield ws


@pytest.mark.asyncio
async def test_write_config(request, full_config, ws):
    config_values = {**full_config, 'profile': request.node.name}
    rpc_request = Request(
        method='config.write',
        params={'values': config_values},
        id=request.node.name,
    )
    await ws.send_str(rpc_request.json())
    rpc_response = SuccessResponse.parse_raw(await ws.receive_str())
    assert rpc_response.id == request.node.name
    assert Config.parse_obj(rpc_response.result) == Config.parse_obj(config_values)


# @pytest.mark.asyncio
# async def test_infer_config(request, full_config, ws):
#     rpc_request = Request(
#         method='config.infer',
#         params={'values': {'profile': request.node.name, 'addon_dir': full_config['addon_dir']}},
#         id=request.node.name,
#     )
#     await ws.send_str(rpc_request.json())
#     rpc_response = SuccessResponse.parse_raw(await ws.receive_str())
#     assert rpc_response.result['profile'] == request.node.name


@pytest.mark.asyncio
async def test_install_with_invalid_params(request, ws):
    rpc_request = Request(
        method='install',
        params={},
        id=request.node.name,
    )
    await ws.send_str(rpc_request.json())
    rpc_response = ErrorResponse.parse_raw(await ws.receive_str())
    assert rpc_response.error['code'] == -32602


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
        id=request.node.name,
    )
    await ws.send_str(rpc_request.json())
    rpc_response = ErrorResponse.parse_raw(await ws.receive_str())
    assert rpc_response.error['code'] == -32001
