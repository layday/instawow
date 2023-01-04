from __future__ import annotations

import re
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import aiohttp.hdrs
import aiohttp.web
import pytest
from aresponses import ResponsesMockServer
from yarl import URL

from instawow._sources.github import GithubResolver
from instawow.common import Defn, Flavour
from instawow.manager import Manager
from instawow.results import PkgFilesNotMatching

ADDON_NAME = 'RaidFadeMore'

ZIPS = {
    'flavoured-toc-only': {
        'toc_files': {
            '_Wrath': b'',
        },
        'flavours': {Flavour.classic},
    },
    'flavoured-and-unflavoured-toc-without-interface-version': {
        'toc_files': {
            '_Wrath': b'',
            '': b'',
        },
        'flavours': {Flavour.classic},
    },
    'flavoured-and-unflavoured-toc-with-interface-version': {
        'toc_files': {
            '_Wrath': b'',
            '': b'## Interface: 11300\n',
        },
        'flavours': {Flavour.vanilla_classic, Flavour.classic},
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


@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [
        {
            URL('//api.github.com/repos/ketho-wow/RaidFadeMore'),
            URL('//api.github.com/repos/ketho-wow/RaidFadeMore/releases?per_page=10'),
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
async def test_package_json_less_addon(
    aresponses: ResponsesMockServer,
    iw_manager: Manager,
    package_json_less_addon: dict[str, Any],
):
    async def handle_request(request: aiohttp.web.Request):
        if aiohttp.hdrs.RANGE in request.headers:
            raise aiohttp.web.HTTPRequestRangeNotSatisfiable

        response = aiohttp.web.Response(body=package_json_less_addon['addon'])
        await response.prepare(request)
        return response

    aresponses.add(
        'api.github.com',
        re.compile(r'^/repos(/[^/]*){2}/releases/assets/'),
        'get',
        handle_request,
        repeat=aresponses.INFINITY,
    )

    try:
        await GithubResolver(iw_manager).resolve_one(
            Defn('github', 'ketho-wow/RaidFadeMore'), None
        )
    except PkgFilesNotMatching:
        assert iw_manager.config.game_flavour not in package_json_less_addon['flavours']
    else:
        assert iw_manager.config.game_flavour in package_json_less_addon['flavours']
