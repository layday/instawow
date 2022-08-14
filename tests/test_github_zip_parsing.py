from __future__ import annotations

from io import BytesIO
import re
from typing import Any
from zipfile import ZipFile

import aiohttp.hdrs
import aiohttp.web
from aresponses import ResponsesMockServer
import pytest

from instawow._sources.github import GithubResolver
from instawow.common import Flavour
from instawow.manager import Manager
from instawow.resolvers import Defn
from instawow.results import PkgFileUnavailable

ADDON_NAME = 'RaidFadeMore'

ZIPS = {
    'flavoured-toc-only': {
        'toc_files': {
            '_TBC': b'',
        },
        'flavours': {Flavour.burning_crusade_classic},
    },
    'flavoured-and-unflavoured-toc-without-interface-version': {
        'toc_files': {
            '_TBC': b'',
            '': b'',
        },
        'flavours': {Flavour.burning_crusade_classic},
    },
    'flavoured-and-unflavoured-toc-with-interface-version': {
        'toc_files': {
            '_TBC': b'',
            '': b'## Interface: 11300\n',
        },
        'flavours': {Flavour.vanilla_classic, Flavour.burning_crusade_classic},
    },
    'unflavoured-toc-only-without-interface-version': {
        'toc_files': {
            '': b'',
        },
        'flavours': set(),
    },
    'unflavoured-toc-only-with-interface-version': {
        'toc_files': {
            '': b'## Interface: 11300\n',
        },
        'flavours': {Flavour.vanilla_classic},
    },
}


@pytest.fixture(params=ZIPS.values(), ids=list(ZIPS))
def package_json_less_addon(
    request: Any,
):
    addon = BytesIO()
    with ZipFile(addon, 'w') as file:
        for flavour_suffix, content in request.param['toc_files'].items():
            file.writestr(f'{ADDON_NAME}/{ADDON_NAME}{flavour_suffix}.toc', content)

    return {
        'addon': addon.getvalue(),
        'flavours': request.param['flavours'],
    }


@pytest.mark.iw_no_mock_http
async def test_package_json_less_addon(
    aresponses: ResponsesMockServer,
    iw_manager: Manager,
    iw_mock_aiohttp_raidfademore_requests: object,
    package_json_less_addon: dict[str, Any],
):
    async def handle_request(request: aiohttp.web.Request):
        if aiohttp.hdrs.RANGE in request.headers:
            raise aiohttp.web.HTTPRequestRangeNotSatisfiable

        response = aiohttp.web.Response(body=package_json_less_addon['addon'])
        await response.prepare(request)
        return response

    aresponses.add(
        'github.com',
        re.compile(r'^(/[^/]*){2}/releases/download'),
        'get',
        handle_request,
        repeat=aresponses.INFINITY,
    )

    try:
        await GithubResolver(iw_manager).resolve_one(
            Defn('github', 'ketho-wow/RaidFadeMore'), None
        )
    except PkgFileUnavailable:
        assert iw_manager.config.game_flavour not in package_json_less_addon['flavours']
    else:
        assert iw_manager.config.game_flavour in package_json_less_addon['flavours']
