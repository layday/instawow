from __future__ import annotations

import logging
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
from instawow.manager_ctx import ManagerCtx
from instawow.pkg_models import Pkg
from instawow.results import PkgFilesMissing, PkgFilesNotMatching, PkgNonexistent


@pytest.fixture
def github_resolver(
    iw_manager_ctx: ManagerCtx,
):
    return GithubResolver(iw_manager_ctx)


zip_defn = Defn('github', '28/NoteworthyII')
zip_addon_name = URL(zip_defn.alias).name


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
            file.writestr(f'{zip_addon_name}/{zip_addon_name}{flavour_suffix}.toc', content)

    return (addon.getvalue(), request.param['flavours'])


@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [
        {
            URL(f'//api.github.com/repos/{zip_defn.alias}'),
            URL(f'//api.github.com/repos/{zip_defn.alias}/releases?per_page=10'),
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
async def test_extracting_flavour_from_zip_contents(
    iw_aresponses: ResponsesMockServer,
    iw_manager_ctx: ManagerCtx,
    github_resolver: GithubResolver,
    package_json_less_addon: tuple[bytes, set[Flavour]],
):
    async def handle_request(request: aiohttp.web.Request):
        if aiohttp.hdrs.RANGE in request.headers:
            raise aiohttp.web.HTTPRequestRangeNotSatisfiable

        response = aiohttp.web.Response(body=addon)
        await response.prepare(request)
        return response

    iw_aresponses.add(
        'api.github.com',
        re.compile(r'^/repos(/[^/]*){2}/releases/assets/'),
        'get',
        handle_request,
        repeat=iw_aresponses.INFINITY,
    )

    addon, flavours = package_json_less_addon
    try:
        await github_resolver.resolve_one(zip_defn, None)
    except PkgFilesNotMatching:
        assert iw_manager_ctx.config.game_flavour not in flavours
    else:
        assert iw_manager_ctx.config.game_flavour in flavours


async def test_repo_with_release_json_release(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'nebularg/PackagerTest')

    result = await github_resolver.resolve_one(defn, None)
    assert type(result) is Pkg


async def test_repo_without_releases(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'AdiAddons/AdiBags')

    with pytest.raises(PkgFilesMissing) as exc_info:
        await github_resolver.resolve_one(defn, None)

    assert exc_info.value.message == 'release not found'


async def test_nonexistent_repo(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'layday/foobar')

    with pytest.raises(PkgNonexistent):
        await github_resolver.resolve_one(defn, None)


async def test_changelog_is_data_url(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'p3lim-wow/Molinari')

    result = await github_resolver.resolve_one(defn, None)
    assert result.changelog_url.startswith('data:,')


@pytest.mark.parametrize(
    ('iw_config_values', 'flavor', 'interface'),
    [
        (Flavour.Retail, 'mainline', 30400),
        (Flavour.Classic, 'wrath', 90207),
        (Flavour.VanillaClassic, 'classic', 90207),
    ],
    indirect=('iw_config_values',),
)
@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [
        {
            URL('//api.github.com/repos/nebularg/PackagerTest'),
            URL('//api.github.com/repos/nebularg/PackagerTest/releases?per_page=10'),
        }
    ],
    indirect=True,
)
async def test_mismatched_release_is_skipped_and_logged(
    caplog: pytest.LogCaptureFixture,
    iw_aresponses: ResponsesMockServer,
    github_resolver: GithubResolver,
    flavor: str,
    interface: int,
):
    iw_aresponses.add(
        'api.github.com',
        re.compile(r'^/repos/nebularg/PackagerTest/releases/assets/'),
        'GET',
        {
            'releases': [
                {
                    'filename': 'TestGit-v1.9.7.zip',
                    'nolib': False,
                    'metadata': [{'flavor': flavor, 'interface': interface}],
                }
            ]
        },
    )

    defn = Defn('github', 'nebularg/PackagerTest')

    with pytest.raises(PkgFilesNotMatching):
        await github_resolver.resolve_one(defn, None)

    (log_record,) = caplog.record_tuples
    assert log_record == (
        'instawow._sources.github',
        logging.INFO,
        f'interface number "{interface}" and flavor "{flavor}" mismatch',
    )


@pytest.mark.parametrize(
    ('url', 'extracted_alias'),
    [
        (
            'https://github.com/AdiAddons/AdiButtonAuras',
            'AdiAddons/AdiButtonAuras',
        ),
        (
            'https://github.com/AdiAddons/AdiButtonAuras/releases',
            'AdiAddons/AdiButtonAuras',
        ),
    ],
)
def test_can_extract_alias_from_url(
    github_resolver: GithubResolver,
    url: str,
    extracted_alias: str,
):
    assert github_resolver.get_alias_from_url(URL(url)) == extracted_alias
