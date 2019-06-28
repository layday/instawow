
import asyncio
from multiprocessing import Process
import os
from typing import List
from unittest.mock import patch

import aiohttp
import pytest

from instawow import api
from instawow.config import Config
from instawow.manager import WsManager
from instawow.models import PkgCoercer, PkgFolderCoercer, PkgOptionsCoercer


PORT = 55439


class Pkg(PkgCoercer):

    folders: List[PkgFolderCoercer]
    options: PkgOptionsCoercer


class FailRequest(api.Request):

    _name = 'fail'

    def prepare_response(self, manager):
        async def raise_():
            raise ValueError

        return raise_()


@pytest.fixture(scope='module', autouse=True)
def config(tmp_path_factory):
    config = Config(config_dir=tmp_path_factory.mktemp(f'{__name__}_config'),
                    addon_dir= tmp_path_factory.mktemp(f'{__name__}_addons'))
    config.write()
    yield config


@pytest.fixture(scope='module', autouse=True)
def environ(config):
    with patch.dict(os.environ, {'INSTAWOW_CONFIG_DIR': str(config.config_dir)}):
        yield



@pytest.fixture(scope='module', autouse=True)
def ws_server(config):
    with patch.dict(api._REQUESTS, {FailRequest._name: FailRequest}):
        process = Process(daemon=True, target=lambda: WsManager().serve(port=PORT))
        process.start()
        process.join(3)         # Effectively ``time.sleep(3)``
        yield


@pytest.fixture
@pytest.mark.asyncio
async def ws_client(ws_server):
    async with aiohttp.ClientSession() as client, \
            client.ws_connect(f'ws://127.0.0.1:{PORT}') as ws:
        yield ws


@pytest.mark.asyncio
async def test_parse_error_error_response(ws_client):
    request = 'foo'
    response = {'jsonrpc': '2.0',
                'id': None,
                'error': {'code': -32700,
                          'message': 'request is not valid JSON',
                          'data': 'Expecting value: line 1 column 1 (char 0)'}}
    await ws_client.send_str('foo')
    assert (await ws_client.receive_json()) == response


@pytest.mark.asyncio
async def test_invalid_request_error_response(ws_client):
    request = []
    response = {'jsonrpc': '2.0',
                'id': None,
                'error': {'code': -32600,
                          'message': 'request is malformed',
                          'data': '[{"loc": ["__obj__"], "msg": "BaseRequest expected dict not '
                                  'list", "type": "type_error"}]'}}
    await ws_client.send_json(request)
    assert (await ws_client.receive_json()) == response


@pytest.mark.asyncio
async def test_method_not_found_error_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_method_not_found_error_response',
               'method': 'foo'}
    response = {'jsonrpc': '2.0',
                'id': 'test_method_not_found_error_response',
                'error': {'code': -32601,
                          'message': 'request method not found',
                          'data': None}}
    await ws_client.send_json(request)
    assert (await ws_client.receive_json()) == response


@pytest.mark.asyncio
async def test_invalid_params_error_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_invalid_params_error_response',
               'method': 'get',
               'params': {}}
    response = {'jsonrpc': '2.0',
                'id': 'test_invalid_params_error_response',
                'error': {'code': -32602,
                          'message': 'request params are invalid',
                          'data': '[{"loc": ["params", "uris"], "msg": "field required", '
                                  '"type": "value_error.missing"}]'}}
    await ws_client.send_json(request)
    assert (await ws_client.receive_json()) == response


@pytest.mark.asyncio
async def test_internal_error_error_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_internal_error_error_response',
               'method': FailRequest._name,
               'params': {}}
    response = {'jsonrpc': '2.0',
                'id': 'test_internal_error_error_response',
                'error': {'code': -32603,
                          'message': 'encountered an internal error',
                          'data': None}}
    await ws_client.send_json(request)
    assert (await ws_client.receive_json()) == response


@pytest.mark.asyncio
async def test_setup_request_response(ws_client, config):
    request = {'jsonrpc': '2.0',
               'id': 'test_setup_request_response',
               'method': 'setup',
               'params': {'addon_dir': str(config.addon_dir)}}
    response = {'jsonrpc': '2.0',
                'id': 'test_setup_request_response',
                'result': {'config': {k: str(v) for k, v in config.__dict__.items()}}}
    await ws_client.send_json(request)
    assert (await ws_client.receive_json()) == response


@pytest.mark.asyncio
async def test_any_manager_error_error_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_any_manager_error_error_response',
               'method': 'resolve',
               'params': {'uri': 'foo:bar', 'resolution_strategy': 'default'}}
    response = {'jsonrpc': '2.0',
                'id': 'test_any_manager_error_error_response',
                'error': {'code': 10027,
                          'message': 'package origin is invalid',
                          'data': None}}
    await ws_client.send_json(request)
    assert (await ws_client.receive_json()) == response


@pytest.mark.asyncio
async def test_get_method_not_installed_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_get_method_not_installed_response',
               'method': 'get',
               'params': {'uris': ['curse:molinari']}}

    await ws_client.send_json(request)
    response = await ws_client.receive_json()
    assert response['id'] == request['id']
    assert api.SuccessResponse.parse_obj(response).result == [None]


@pytest.mark.asyncio
async def test_resolve_method_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_resolve_method_response',
               'method': 'resolve',
               'params': {'uri': 'curse:molinari', 'resolution_strategy': 'default'}}

    await ws_client.send_json(request)
    response = await ws_client.receive_json()
    assert response['id'] == request['id']
    api.SuccessResponse.parse_obj(response)
    pkg = Pkg.parse_obj(response['result'])
    assert pkg.folders == []


@pytest.mark.asyncio
async def test_resolve_method_with_url_in_uri_param_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_resolve_method_with_url_in_uri_param_response',
               'method': 'resolve',
               'params': {'uri': 'https://www.curseforge.com/wow/addons/molinari',
                          'resolution_strategy': 'default'}}

    await ws_client.send_json(request)
    response = await ws_client.receive_json()
    assert response['id'] == request['id']
    assert response['result']['origin'] == 'curse'
    assert response['result']['slug'] == 'molinari'


@pytest.mark.asyncio
async def test_install_method_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_install_method_response',
               'method': 'install',
               'params': {'uri': 'curse:molinari', 'resolution_strategy': 'default',
                          'overwrite': False}}

    await ws_client.send_json(request)
    response = api.SuccessResponse.parse_obj(await ws_client.receive_json())
    assert response.id == request['id']
    Pkg.parse_obj(response.result)


@pytest.mark.asyncio
async def test_get_method_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_get_method_response',
               'method': 'get',
               'params': {'uris': ['curse:molinari']}}

    await ws_client.send_json(request)
    response = await ws_client.receive_json()
    assert response['id'] == request['id']
    assert len(api.SuccessResponse.parse_obj(response).result) == 1
    pkg = Pkg.parse_obj(response['result'][0])
    assert len(pkg.folders) > 0


@pytest.mark.asyncio
async def test_remove_method_response(ws_client):
    request = {'jsonrpc': '2.0',
               'id': 'test_remove_method_response',
               'method': 'remove',
               'params': {'uri': 'curse:molinari'}}

    await ws_client.send_json(request)
    response = api.SuccessResponse.parse_obj(await ws_client.receive_json())
    assert response.id == request['id']
    assert response.result is None
