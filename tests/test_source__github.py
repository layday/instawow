from __future__ import annotations

import logging
from io import BytesIO
from typing import Literal
from zipfile import ZipFile

import aiohttp.hdrs
import aiohttp.web
import pytest
from yarl import URL

from instawow import config_ctx
from instawow._sources.github import GithubResolver, _PackagerReleaseJsonFlavor
from instawow.definitions import Defn, Strategies, Strategy
from instawow.results import PkgFilesMissing, PkgFilesNotMatching, PkgNonexistent
from instawow.wow_installations import (
    FlavourVersions,
    Track,
    to_flavour,
    to_flavour_versions,
    to_flavourful_enum,
)

from ._fixtures.http import AddRoutes, Route

pytestmark = pytest.mark.usefixtures('_iw_config_ctx', '_iw_web_client_ctx')


@pytest.fixture
def github_resolver():
    return GithubResolver()


zip_defn = Defn('github', '28/NoteworthyII')
zip_addon_name = URL(zip_defn.alias).name

packager_test_defn = Defn('github', 'nebularg/PackagerTest')


ZIPS = {
    'flavoured-toc-only': {
        'toc_files': {
            '_Cata': b'',
        },
        'tracks': {Track.Classic},
    },
    'flavoured-and-unflavoured-toc-without-interface-version': {
        'toc_files': {
            '_Cata': b'',
            '': b'',
        },
        'tracks': {Track.Classic},
    },
    'flavoured-and-unflavoured-toc-with-interface-version': {
        'toc_files': {
            '_Cata': b'',
            '': b'## Interface: 11300\n',
        },
        'tracks': {Track.VanillaClassic, Track.Classic},
    },
    'unflavoured-toc-only-without-interface-version': {
        'toc_files': {
            '': b'',
        },
        'tracks': set[Track](),
    },
    'unflavoured-toc-only-with-interface-version': {
        'toc_files': {
            '': b'## Interface: 11300\n',
        },
        'tracks': {Track.VanillaClassic},
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

    return (addon.getvalue(), request.param['tracks'])


@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [
        {
            rf'//api\.github\.com/repos/{zip_defn.alias}',
            rf'//api\.github\.com/repos/{zip_defn.alias}/releases\?per_page=10',
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    'iw_profile_config_values',
    Track,
    indirect=True,
)
async def test_extracting_flavour_from_zip_contents(
    iw_add_routes: AddRoutes,
    github_resolver: GithubResolver,
    package_json_less_addon: tuple[bytes, set[Track]],
):
    async def handle_request(request: aiohttp.web.BaseRequest):
        if aiohttp.hdrs.RANGE in request.headers:
            raise aiohttp.web.HTTPRequestRangeNotSatisfiable

        response = aiohttp.web.Response(body=addon)
        await response.prepare(request)
        return response

    iw_add_routes(
        Route(
            r'//api\.github\.com/repos(/[^/]*){2}/releases/assets/.*',
            handle_request,
        )
    )

    addon, tracks = package_json_less_addon
    try:
        await github_resolver.resolve_one(zip_defn, None)
    except PkgFilesNotMatching:
        assert config_ctx.config().track not in tracks
    else:
        assert config_ctx.config().track in tracks


async def test_repo_with_release_json_release(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'nebularg/PackagerTest')

    result = await github_resolver.resolve_one(defn, None)
    assert type(result) is dict


async def test_repo_without_releases(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'AdiAddons/AdiBags')

    with pytest.raises(PkgFilesMissing) as exc_info:
        await github_resolver.resolve_one(defn, None)

    assert str(exc_info.value) == 'no releases found'


async def test_nonexistent_repo(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'layday/foobar')

    with pytest.raises(PkgNonexistent):
        await github_resolver.resolve_one(defn, None)


@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [
        {
            rf'//api\.github\.com/repos/{packager_test_defn.alias}',
            rf'//api\.github\.com/repos/{packager_test_defn.alias}/releases\?per_page=10',
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize('any_flavour', [True, None])
async def test_any_flavour_strategy(
    iw_add_routes: AddRoutes,
    github_resolver: GithubResolver,
    any_flavour: Literal[True, None],
):
    wrong_flavour = next(
        f for f in FlavourVersions if f is not to_flavour_versions(config_ctx.config().track)
    )
    wrong_interface = next(n for r in wrong_flavour.value for n in r)

    iw_add_routes(
        Route(
            r'//api\.github\.com/repos/nebularg/PackagerTest/releases/assets/.*',
            {
                'releases': [
                    {
                        'filename': 'TestGit-v1.9.7.zip',
                        'nolib': False,
                        'metadata': [
                            {
                                'flavor': to_flavourful_enum(
                                    wrong_flavour, _PackagerReleaseJsonFlavor
                                ),
                                'interface': wrong_interface,
                            }
                        ],
                    }
                ]
            },
        )
    )
    defn = Defn(
        'github',
        'nebularg/PackagerTest',
        strategies=Strategies({Strategy.AnyFlavour: any_flavour}),
    )

    results = await github_resolver.resolve([defn])
    assert type(results[defn]) is (dict if any_flavour else PkgFilesNotMatching)


async def test_changelog_is_data_url(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'sfx-wow/masque')

    result = await github_resolver.resolve_one(defn, None)
    assert result['changelog_url'].startswith('data:,')


@pytest.mark.parametrize(
    ('iw_profile_config_values', 'flavor', 'interface'),
    [
        (Track.Retail, 'mainline', 30400),
        (Track.Classic, 'mists', 90207),
        (Track.VanillaClassic, 'classic', 90207),
    ],
    indirect=('iw_profile_config_values',),
)
@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [
        {
            rf'//api\.github\.com/repos/{packager_test_defn.alias}',
            rf'//api\.github\.com/repos/{packager_test_defn.alias}/releases\?per_page=10',
        }
    ],
    indirect=True,
)
async def test_mismatched_release_is_skipped_and_logged(
    caplog: pytest.LogCaptureFixture,
    iw_add_routes: AddRoutes,
    github_resolver: GithubResolver,
    flavor: str,
    interface: int,
):
    iw_add_routes(
        Route(
            r'//api\.github\.com/repos/nebularg/PackagerTest/releases/assets/.*',
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
    )

    with pytest.raises(PkgFilesNotMatching):
        await github_resolver.resolve_one(packager_test_defn, None)

    assert (
        'instawow._sources.github',
        logging.INFO,
        f'Flavor and interface mismatch: {(interface, to_flavour(config_ctx.config().track))}',
    ) in caplog.record_tuples


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
