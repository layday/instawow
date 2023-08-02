from __future__ import annotations

import re
from io import BytesIO
from zipfile import ZipFile

import aiohttp.hdrs
import aiohttp.web
import pytest
from aresponses import ResponsesMockServer
from yarl import URL

from instawow._sources.github import GithubResolver
from instawow.common import Defn, Flavour
from instawow.results import PkgFilesNotMatching
from tests.conftest import ManagerCtx

defn = Defn('github', '28/NoteworthyII')
addon_name = URL(defn.alias).name


ZIPS = {
    'flavoured-toc-only': {
        'toc_files': {
            '_Wrath': b'',
        },
        'flavours': {Flavour.Classic},
    },
    'flavoured-and-unflavoured-toc-without-interface-version': {
        'toc_files': {
            '_Wrath': b'',
            '': b'',
        },
        'flavours': {Flavour.Classic},
    },
    'flavoured-and-unflavoured-toc-with-interface-version': {
        'toc_files': {
            '_Wrath': b'',
            '': b'## Interface: 11300\n',
        },
        'flavours': {Flavour.VanillaClassic, Flavour.Classic},
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
        'flavours': {Flavour.VanillaClassic},
    },
}


@pytest.fixture(params=ZIPS.values(), ids=list(ZIPS))
def package_json_less_addon(
    request: pytest.FixtureRequest,
):
    addon = BytesIO()

    with ZipFile(addon, 'w') as file:
        for flavour_suffix, content in request.param['toc_files'].items():
            file.writestr(f'{addon_name}/{addon_name}{flavour_suffix}.toc', content)

    return (addon.getvalue(), request.param['flavours'])


@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [
        {
            URL(f'//api.github.com/repos/{defn.alias}'),
            URL(f'//api.github.com/repos/{defn.alias}/releases?per_page=10'),
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
    iw_manager_ctx: ManagerCtx,
    package_json_less_addon: tuple[bytes, set[Flavour]],
):
    async def handle_request(request: aiohttp.web.Request):
        if aiohttp.hdrs.RANGE in request.headers:
            raise aiohttp.web.HTTPRequestRangeNotSatisfiable

        response = aiohttp.web.Response(body=addon)
        await response.prepare(request)
        return response

    aresponses.add(
        'api.github.com',
        re.compile(r'^/repos(/[^/]*){2}/releases/assets/'),
        'get',
        handle_request,
        repeat=aresponses.INFINITY,
    )

    addon, flavours = package_json_less_addon
    try:
        await GithubResolver(iw_manager_ctx).resolve_one(defn, None)
    except PkgFilesNotMatching:
        assert iw_manager_ctx.config.game_flavour not in flavours
    else:
        assert iw_manager_ctx.config.game_flavour in flavours
