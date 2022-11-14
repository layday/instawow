# pyright: strict

from __future__ import annotations

import json
import re
from collections.abc import Callable
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from aiohttp.web import Response
from attr import frozen
from yarl import URL

from instawow import __version__

_HERE = Path(__file__).parent

_match_any = re.compile(r'.*')


def _load_fixture(filename: str):
    return (_HERE / filename).read_bytes()


def _load_json_fixture(filename: str):
    return json.loads(_load_fixture(filename))


@cache
def _make_addon_zip(*folders: str):
    buffer = BytesIO()
    with ZipFile(buffer, 'w') as file:
        for folder in folders:
            file.writestr(f'{folder}/{folder}.toc', b'')

    return buffer.getvalue()


@frozen
class Route:
    url: URL
    response: Callable[[], Response] | dict[str, Any] | str
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
            return re.compile(fr'^{re.escape(self.url.path_qs)}$', re.IGNORECASE)

        return self.url.path_qs

    def to_aresponses_add_args(self) -> dict[str, Any]:
        return {
            'host_pattern': self.url.host,
            'path_pattern': self._make_path_pattern(),
            'method_pattern': self.method,
            'body_pattern': _match_any if self.body_pattern is None else self.body_pattern,
            'match_querystring': self.match_querystring,
            'repeat': self.repeat,
            'response': self.response() if callable(self.response) else self.response,
        }


def _make_route_dict_entry(route: Route):
    return (route.url, route)


ROUTES = dict(
    map(
        _make_route_dict_entry,
        [
            Route(
                URL('//pypi.org/pypi/instawow/json'),
                {'info': {'version': __version__}},
            ),
            Route(
                URL(
                    '//raw.githubusercontent.com/layday/instawow-data/data/base-catalogue-v7.compact.json'
                ),
                _load_json_fixture('base-catalogue-v7.compact.json'),
            ),
            Route(
                URL('//api.curseforge.com/v1/mods'),
                _load_json_fixture('curse-addon--all.json'),
                method='POST',
            ),
            Route(
                URL('//api.curseforge.com/v1/mods/20338/files'),
                _load_json_fixture('curse-addon-files.json'),
            ),
            Route(
                URL('//api.curseforge.com/v1/mods/20338/files/{id}/changelog'),
                _load_json_fixture('curse-addon-changelog.json'),
                path_pattern=re.compile(r'^/v1/mods/20338/files/(\d+)/changelog$'),
            ),
            Route(
                URL('//edge.forgecdn.net'),
                lambda: Response(body=_make_addon_zip('Molinari')),
                path_pattern=_match_any,
            ),
            Route(
                URL('//api.mmoui.com/v3/game/WOW/filelist.json'),
                _load_json_fixture('wowi-filelist.json'),
            ),
            Route(
                URL('//api.mmoui.com/v3/game/WOW/filedetails/{id}.json'),
                _load_json_fixture('wowi-filedetails.json'),
                path_pattern=re.compile(r'^/v3/game/WOW/filedetails/(\d*)\.json$'),
            ),
            Route(
                URL('//cdn.wowinterface.com'),
                lambda: Response(body=_make_addon_zip('Molinari')),
                path_pattern=_match_any,
            ),
            Route(
                URL('//www.tukui.org/api.php?ui=tukui'),
                _load_json_fixture('tukui-ui--tukui.json'),
                match_querystring=True,
            ),
            Route(
                URL('//www.tukui.org/api.php?ui=elvui'),
                _load_json_fixture('tukui-ui--elvui.json'),
                match_querystring=True,
            ),
            Route(
                URL('//www.tukui.org/api.php?addons='),
                _load_json_fixture('tukui-retail-addons.json'),
                match_querystring=True,
            ),
            Route(
                URL('//www.tukui.org/api.php?classic-addons='),
                _load_json_fixture('tukui-classic-addons.json'),
                match_querystring=True,
            ),
            Route(
                URL('//www.tukui.org/api.php?classic-wotlk-addons='),
                _load_json_fixture('tukui-classic-wotlk-addons.json'),
                match_querystring=True,
            ),
            Route(
                URL('//www.tukui.org/downloads/tukui'),
                lambda: Response(body=_make_addon_zip('Tukui')),
                path_pattern=re.compile(r'^/downloads/tukui'),
            ),
            Route(
                URL('//www.tukui.org/addons.php?download=1'),
                lambda: Response(body=_make_addon_zip('ElvUI_MerathilisUI')),
                match_querystring=True,
            ),
            Route(
                URL('//www.tukui.org/classic-addons.php?download=1'),
                lambda: Response(body=_make_addon_zip('Tukui')),
                match_querystring=True,
            ),
            Route(
                URL('//api.github.com/repos/nebularg/PackagerTest'),
                _load_json_fixture('github-repo-release-json.json'),
            ),
            Route(
                URL('//api.github.com/repos/nebularg/PackagerTest/releases?per_page=10'),
                _load_json_fixture('github-release-release-json.json'),
                match_querystring=True,
            ),
            Route(
                URL('//api.github.com/repos/nebularg/PackagerTest/releases/assets/37156458'),
                _load_json_fixture('github-release-release-json-release-json.json'),
            ),
            Route(
                URL('//api.github.com/repos/p3lim-wow/Molinari'),
                _load_json_fixture('github-repo-molinari.json'),
                case_insensitive=True,
            ),
            Route(
                URL('//api.github.com/repos/p3lim-wow/Molinari/releases?per_page=10'),
                _load_json_fixture('github-release-molinari.json'),
                case_insensitive=True,
                match_querystring=True,
            ),
            Route(
                URL('//api.github.com/repos/p3lim-wow/Molinari/releases/assets/57617676'),
                _load_json_fixture('github-release-molinari-release-json.json'),
                case_insensitive=True,
            ),
            Route(
                URL('//api.github.com/repos/AdiAddons/AdiBags'),
                _load_json_fixture('github-repo-no-releases.json'),
            ),
            Route(
                URL('//api.github.com/repos/AdiAddons/AdiBags/releases?per_page=10'),
                lambda: Response(body=b'', status=404),
                match_querystring=True,
            ),
            Route(
                URL('//api.github.com/repos/AdiAddons/AdiButtonAuras/releases/tags/2.0.19'),
                _load_json_fixture('github-release-no-assets.json'),
            ),
            Route(
                URL('//api.github.com/repos/layday/foobar'),
                lambda: Response(body=b'', status=404),
            ),
            Route(
                URL('//api.github.com/repos/{x}/{y}/releases/asssets/{z}'),
                lambda: Response(body=_make_addon_zip('Foo')),
                path_pattern=re.compile(r'^/repos(/[^/]*){2}/releases/assets/'),
            ),
            Route(
                URL('//github.com/login/device/code'),
                _load_json_fixture('github-oauth-login-device-code.json'),
                method='POST',
            ),
            Route(
                URL('//github.com/login/oauth/access_token'),
                _load_json_fixture('github-oauth-login-access-token.json'),
                method='POST',
            ),
            Route(
                URL('//api.github.com/repos/ketho-wow/RaidFadeMore'),
                _load_json_fixture('github-repo-no-release-json.json'),
            ),
            Route(
                URL('//api.github.com/repos/ketho-wow/RaidFadeMore/releases?per_page=10'),
                _load_json_fixture('github-release-no-release-json.json'),
                match_querystring=True,
            ),
            Route(
                URL('//addons.wago.io/api/external/addons/_match'),
                _load_json_fixture('wago-match-addons.json'),
                method='POST',
            ),
        ],
    )
)
