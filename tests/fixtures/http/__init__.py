# pyright: strict

from __future__ import annotations

import importlib.resources
import json
import re
from collections.abc import Awaitable, Callable
from functools import cache
from io import BytesIO
from typing import Any
from zipfile import ZipFile

import attrs
from aiohttp.web import Request, Response
from yarl import URL

from instawow._version_check import get_version

_match_any = re.compile(r'.*')


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


@attrs.frozen
class Route:
    url: URL = attrs.field(converter=URL)
    response: (
        Response
        | Callable[[Request], Response]
        | Callable[[Request], Awaitable[Response]]
        | dict[str, Any]
        | str
    )
    path_pattern: re.Pattern[str] | None = None
    method: str = 'GET'
    body_pattern: re.Pattern[str] | None = None
    match_querystring: bool = False
    repeat: float = float('inf')
    case_insensitive: bool = False

    def _make_path_pattern(self):
        if self.path_pattern is not None:
            return self.path_pattern

        if self.case_insensitive:
            return re.compile(rf'^{re.escape(self.url.path_qs)}$', re.IGNORECASE)

        return self.url.path_qs

    def to_aresponses_add_args(self) -> dict[str, Any]:
        return {
            'host_pattern': self.url.host,
            'path_pattern': self._make_path_pattern(),
            'method_pattern': self.method,
            'body_pattern': _match_any if self.body_pattern is None else self.body_pattern,
            'match_querystring': self.match_querystring,
            'repeat': self.repeat,
            'response': self.response,
        }


ROUTES = {
    r.url: r
    for r in (
        Route(
            '//pypi.org/pypi/instawow/json',
            {'info': {'version': get_version()}},
        ),
        Route(
            '//raw.githubusercontent.com/layday/instawow-data/data/base-catalogue-v7.compact.json',
            _load_json_fixture('base-catalogue-v7.compact.json'),
        ),
        Route(
            '//api.curseforge.com/v1/mods',
            _load_json_fixture('curse-addon--all.json'),
            method='POST',
        ),
        Route(
            '//api.curseforge.com/v1/mods/search?gameId=1&slug=molinari',
            _load_json_fixture('curse-addon-slug-search.json'),
            match_querystring=True,
        ),
        Route(
            '//api.curseforge.com/v1/mods/20338/files',
            _load_json_fixture('curse-addon-files.json'),
        ),
        Route(
            '//api.curseforge.com/v1/mods/20338/files/4419396',
            _load_json_fixture('curse-addon-file-4419396.json'),
        ),
        Route(
            '//api.curseforge.com/v1/mods/20338/files/5090686',
            _load_json_fixture('curse-addon-file-5090686.json'),
        ),
        Route(
            '//api.curseforge.com/v1/mods/20338/files/{id}/changelog',
            _load_json_fixture('curse-addon-changelog.json'),
            path_pattern=re.compile(r'^/v1/mods/20338/files/(\d+)/changelog$'),
        ),
        Route(
            '//edge.forgecdn.net',
            lambda _: Response(body=_make_addon_zip('Molinari')),
            path_pattern=_match_any,
        ),
        Route(
            '//api.mmoui.com/v3/game/WOW/filelist.json',
            _load_json_fixture('wowi-filelist.json'),
        ),
        Route(
            '//api.mmoui.com/v3/game/WOW/filedetails/{id}.json',
            _load_json_fixture('wowi-filedetails.json'),
            path_pattern=re.compile(r'^/v3/game/WOW/filedetails/(\d*)\.json$'),
        ),
        Route(
            '//cdn.wowinterface.com',
            lambda _: Response(body=_make_addon_zip('Molinari')),
            path_pattern=_match_any,
        ),
        Route(
            '//api.tukui.org/v1/addon/tukui',
            _load_json_fixture('tukui-ui--tukui.json'),
        ),
        Route(
            '//api.tukui.org/v1/addon/elvui',
            _load_json_fixture('tukui-ui--elvui.json'),
        ),
        Route(
            '//api.tukui.org/v1/download/',
            lambda _: Response(body=_make_addon_zip('Tukui')),
            path_pattern=re.compile(r'^/v1/download/'),
        ),
        Route(
            '//api.github.com/repos/nebularg/PackagerTest',
            _load_json_fixture('github-repo-release-json.json'),
        ),
        Route(
            '//api.github.com/repos/nebularg/PackagerTest/releases?per_page=10',
            _load_json_fixture('github-release-release-json.json'),
            match_querystring=True,
        ),
        Route(
            '//api.github.com/repos/nebularg/PackagerTest/releases/assets/37156458',
            _load_json_fixture('github-release-release-json-release-json.json'),
        ),
        Route(
            '//api.github.com/repositories/388670',
            _load_json_fixture('github-repo-molinari.json'),
        ),
        Route(
            '//api.github.com/repos/p3lim-wow/Molinari',
            _load_json_fixture('github-repo-molinari.json'),
            case_insensitive=True,
        ),
        Route(
            '//api.github.com/repositories/388670/releases?per_page=10',
            _load_json_fixture('github-release-molinari.json'),
            case_insensitive=True,
            match_querystring=True,
        ),
        Route(
            '//api.github.com/repos/p3lim-wow/Molinari/releases?per_page=10',
            _load_json_fixture('github-release-molinari.json'),
            case_insensitive=True,
            match_querystring=True,
        ),
        Route(
            URL(
                next(
                    a['url']
                    for a in _load_json_fixture('github-release-molinari.json')[0]['assets']
                    if a['name'] == 'release.json'
                )
            ).with_scheme(''),
            _load_json_fixture('github-release-molinari-release-json.json'),
            case_insensitive=True,
        ),
        Route(
            '//api.github.com/repos/AdiAddons/AdiBags',
            _load_json_fixture('github-repo-no-releases.json'),
        ),
        Route(
            '//api.github.com/repos/AdiAddons/AdiBags/releases?per_page=10',
            lambda _: Response(body=b'', status=404),
            match_querystring=True,
        ),
        Route(
            '//api.github.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19',
            _load_json_fixture('github-release-no-assets.json'),
        ),
        Route(
            '//api.github.com/repos/layday/foobar',
            lambda _: Response(body=b'', status=404),
        ),
        Route(
            '//api.github.com/repos/{x}/{y}/releases/asssets/{z}',
            lambda _: Response(body=_make_addon_zip('Molinari')),
            path_pattern=re.compile(r'^/repos(/[^/]*){2}/releases/assets/'),
        ),
        Route(
            '//github.com/login/device/code',
            _load_json_fixture('github-oauth-login-device-code.json'),
            method='POST',
        ),
        Route(
            '//github.com/login/oauth/access_token',
            _load_json_fixture('github-oauth-login-access-token.json'),
            method='POST',
        ),
        Route(
            '//api.github.com/repos/28/NoteworthyII',
            _load_json_fixture('github-repo-no-release-json.json'),
        ),
        Route(
            '//api.github.com/repos/28/NoteworthyII/releases?per_page=10',
            _load_json_fixture('github-release-no-release-json.json'),
            match_querystring=True,
        ),
    )
}
