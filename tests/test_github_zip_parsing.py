from __future__ import annotations

from io import BytesIO
import re
from typing import Any
from zipfile import ZipFile

from aresponses import ResponsesMockServer
import pytest

from instawow.common import Flavour
from instawow.manager import Manager
from instawow.resolvers import Defn, GithubResolver
from instawow.results import PkgFileUnavailable

ZIPS = {
    'flavoured-toc-only': {
        'files': {
            'Foo/Foo_TBC.toc': b'',
        },
        'flavours': {Flavour.burning_crusade_classic},
    },
    'flavoured-and-unflavoured-toc-without-interface-version': {
        'files': {'Foo/Foo_TBC.toc': b'', 'Foo/Foo.toc': b''},
        'flavours': {Flavour.burning_crusade_classic},
    },
    'flavoured-and-unflavoured-toc-with-interface-version': {
        'files': {
            'Foo/Foo_TBC.toc': b'',
            'Foo/Foo.toc': b'# Interface: 11300\n',
        },
        'flavours': {Flavour.vanilla_classic, Flavour.burning_crusade_classic},
    },
    'unflavoured-toc-only-without-interface-version': {
        'files': {
            'Foo/Foo.toc': b'',
        },
        'flavours': set(),
    },
    'unflavoured-toc-only-with-interface-version': {
        'files': {
            'Foo/Foo.toc': b'# Interface: 11300\n',
        },
        'flavours': {Flavour.vanilla_classic},
    },
}


@pytest.fixture(params=ZIPS.values(), ids=ZIPS.keys())
def package_json_less_addon(
    request: pytest.FixtureRequest,
):
    addon = BytesIO()
    with ZipFile(addon, 'w') as file:
        for filename, content in request.param['files'].items():
            file.writestr(filename, content)

    return {
        'addon': addon.getvalue(),
        'flavours': request.param['flavours'],
    }


@pytest.mark.xfail
async def test_package_json_less_addon(
    aresponses: ResponsesMockServer,
    iw_manager: Manager,
    package_json_less_addon: dict[str, Any],
):
    aresponses.add(
        'github.com',
        re.compile(r'^(/[^/]*){2}/releases/download'),
        'get',
        aresponses.Response(body=package_json_less_addon['addon']),
    )

    try:
        await GithubResolver(iw_manager).resolve_one(
            Defn('github', 'ketho-wow/RaidFadeMore'), None
        )
    except PkgFileUnavailable:
        assert iw_manager.config.game_flavour not in package_json_less_addon['flavours']
    else:
        assert iw_manager.config.game_flavour in package_json_less_addon['flavours']
