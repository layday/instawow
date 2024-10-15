from __future__ import annotations

import importlib.resources
import json
import re
from functools import cache
from io import BytesIO
from zipfile import ZipFile

from instawow._version import get_version

from ._mock_server import Response, Route
from ._mock_server import ResponsesMockServer as ResponsesMockServer


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
            r'//raw\.githubusercontent\.com/layday/instawow-data/data/base-catalogue-v7\.compact\.json',
            _load_json_fixture('base-catalogue-v7.compact.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods',
            _load_json_fixture('curse-addon--all.json'),
            method='POST',
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/search\?gameId=1&slug=molinari',
            _load_json_fixture('curse-addon-slug-search.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/20338/files',
            _load_json_fixture('curse-addon-files.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/20338/files/4419396',
            _load_json_fixture('curse-addon-file-4419396.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/20338/files/5090686',
            _load_json_fixture('curse-addon-file-5090686.json'),
        ),
        Route(
            r'//api\.curseforge\.com/v1/mods/20338/files/(\d+)/changelog',
            _load_json_fixture('curse-addon-changelog.json'),
        ),
        Route(
            r'//edge\.forgecdn\.net/.*',
            lambda _: Response(body=_make_addon_zip('Molinari')),
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
            lambda _: Response(body=_make_addon_zip('Molinari')),
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
            lambda _: Response(body=_make_addon_zip('Tukui')),
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
            r'//api\.github\.com/repositories/388670',
            _load_json_fixture('github-repo-molinari.json'),
        ),
        Route(
            r'//api\.github\.com/repos/p3lim-wow/Molinari',
            _load_json_fixture('github-repo-molinari.json'),
        ),
        Route(
            r'//api\.github\.com/repositories/388670/releases\?per_page=10',
            _load_json_fixture('github-release-molinari.json'),
        ),
        Route(
            r'//api\.github\.com/repos/p3lim-wow/Molinari/releases\?per_page=10',
            _load_json_fixture('github-release-molinari.json'),
        ),
        Route(
            re.escape(
                next(
                    a['url']
                    for a in _load_json_fixture('github-release-molinari.json')[0]['assets']
                    if a['name'] == 'release.json'
                )
            ),
            _load_json_fixture('github-release-molinari-release-json.json'),
        ),
        Route(
            r'//api\.github\.com/repos/AdiAddons/AdiBags',
            _load_json_fixture('github-repo-no-releases.json'),
        ),
        Route(
            r'//api\.github\.com/repos/AdiAddons/AdiBags/releases\?per_page=10',
            lambda _: Response(body=b'', status=404),
        ),
        Route(
            r'//api\.github\.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2\.0\.19',
            _load_json_fixture('github-release-no-assets.json'),
        ),
        Route(
            r'//api\.github\.com/repos/layday/foobar',
            lambda _: Response(body=b'', status=404),
        ),
        Route(
            r'//api\.github\.com/repos(/[^/]*){2}/releases/assets/.*',
            lambda _: Response(body=_make_addon_zip('Molinari')),
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
