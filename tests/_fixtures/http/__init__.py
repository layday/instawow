from __future__ import annotations

import importlib.resources
import json
import re
from functools import cache
from io import BytesIO
from zipfile import ZipFile

from instawow._version import get_version

from ._mock_server import AddRoutes as AddRoutes
from ._mock_server import Response
from ._mock_server import Route as Route
from ._mock_server import patch_aiohttp as patch_aiohttp
from ._mock_server import prepare_mock_server_router as prepare_mock_server_router


def _load_fixture(filename: str):
    return (importlib.resources.files(__spec__.parent) / filename).read_bytes()


def _load_json_fixture(filename: str):
    return json.loads(_load_fixture(filename))


@cache
def _make_addon_zip(*folders: str):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as file:
        for folder in folders:
            file.writestr(f'{folder}/{folder}.toc', b'')

    return buffer.getvalue()


ROUTES = {
    r.url: r
    for r in (
        Route(
            r'//pypi\.org/pypi/instawow/json',
            {'info': {'version': get_version()}},
        ),
        Route(
            r'//raw\.githubusercontent\.com/layday/instawow-data/data/base-catalogue-v8\.compact\.json',
            _load_json_fixture('base-catalogue-v8.compact.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods',
            _load_json_fixture('curse-addon--all.json'),
            method='POST',
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/search\?gameId=1&slug=masque',
            _load_json_fixture('curse-addon-slug-search.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/13592/files',
            _load_json_fixture('curse-addon-files.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/13592/files/6454541',
            _load_json_fixture('curse-addon-file-6454541.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/13592/files/5810397',
            _load_json_fixture('curse-addon-file-5810397.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/13592/files/(\d+)/changelog',
            _load_json_fixture('curse-addon-changelog.json'),
        ),
        Route(
            r'//edge\.forgecdn\.net/.*',
            lambda: Response(body=_make_addon_zip('Masque')),
        ),
        Route(
            r'//api\.mmoui\.com/v3/game/WOW/filelist\.json',
            _load_json_fixture('wowi-filelist.json'),
        ),
        Route(
            r'//api\.mmoui\.com/v3/game/WOW/filedetails/(\d*)\.json',
            _load_json_fixture('wowi-filedetails.json'),
        ),
        Route(
            r'//cdn\.wowinterface\.com/.*',
            lambda: Response(body=_make_addon_zip('Masque')),
        ),
        Route(
            r'//api\.tukui\.org/v1/addon/tukui',
            _load_json_fixture('tukui-ui--tukui.json'),
        ),
        Route(
            r'//api\.tukui\.org/v1/addon/elvui',
            _load_json_fixture('tukui-ui--elvui.json'),
        ),
        Route(
            r'//api\.tukui\.org/v1/download/.*',
            lambda: Response(body=_make_addon_zip('Tukui')),
        ),
        Route(
            r'//api\.github\.com/repos/nebularg/PackagerTest',
            _load_json_fixture('github-repo-release-json.json'),
        ),
        Route(
            r'//api\.github\.com/repos/nebularg/PackagerTest/releases\?per_page=10',
            _load_json_fixture('github-release-release-json.json'),
        ),
        Route(
            r'//api\.github\.com/repos/nebularg/PackagerTest/releases/assets/37156458',
            _load_json_fixture('github-release-release-json-release-json.json'),
        ),
        Route(
            r'//api\.github\.com/repositories/44074003',
            _load_json_fixture('github-repo-masque.json'),
        ),
        Route(
            r'//api\.github\.com/repos/SFX-WoW/Masque',
            _load_json_fixture('github-repo-masque.json'),
        ),
        Route(
            r'//api\.github\.com/repositories/44074003/releases\?per_page=10',
            _load_json_fixture('github-release-masque.json'),
        ),
        Route(
            r'//api\.github\.com/repos/SFX-WoW/Masque/releases\?per_page=10',
            _load_json_fixture('github-release-masque.json'),
        ),
        Route(
            re.escape(
                next(
                    a['url']
                    for r in _load_json_fixture('github-release-masque.json')
                    if not r['prerelease']
                    for a in r['assets']
                    if a['name'] == 'release.json'
                )
            ),
            _load_json_fixture('github-release-masque-release-json.json'),
        ),
        Route(
            r'//api\.github\.com/repos/AdiAddons/AdiBags',
            _load_json_fixture('github-repo-no-releases.json'),
        ),
        Route(
            r'//api\.github\.com/repos/AdiAddons/AdiBags/releases\?per_page=10',
            lambda: Response(body=b'', status=404),
        ),
        Route(
            r'//api\.github\.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2\.0\.19',
            _load_json_fixture('github-release-no-assets.json'),
        ),
        Route(
            r'//api\.github\.com/repos/layday/foobar',
            lambda: Response(body=b'', status=404),
        ),
        Route(
            r'//api\.github\.com/repos(/[^/]*){2}/releases/assets/.*',
            lambda: Response(body=_make_addon_zip('Masque')),
        ),
        Route(
            r'//github\.com/login/device/code',
            _load_json_fixture('github-oauth-login-device-code.json'),
            method='POST',
        ),
        Route(
            r'//github\.com/login/oauth/access_token',
            _load_json_fixture('github-oauth-login-access-token.json'),
            method='POST',
        ),
        Route(
            r'//api\.github\.com/repos/28/NoteworthyII',
            _load_json_fixture('github-repo-no-release-json.json'),
        ),
        Route(
            r'//api\.github\.com/repos/28/NoteworthyII/releases\?per_page=10',
            _load_json_fixture('github-release-no-release-json.json'),
        ),
    )
}
