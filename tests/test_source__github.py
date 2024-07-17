from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Literal
from zipfile import ZipFile

import aiohttp.hdrs
import aiohttp.web
import aresponses
import pytest
from yarl import URL

from instawow._sources.github import GithubResolver
from instawow.definitions import Defn, Strategies, Strategy
from instawow.pkg_models import Pkg
from instawow.results import PkgFilesMissing, PkgFilesNotMatching, PkgNonexistent
from instawow.shared_ctx import ConfigBoundCtx
from instawow.wow_installations import Flavour, FlavourVersionRange

from .fixtures.http import Route


@pytest.fixture
def github_resolver(
    iw_config_ctx: ConfigBoundCtx,
):
    return GithubResolver(iw_config_ctx.config)


zip_defn = Defn('github', '28/NoteworthyII')
zip_addon_name = URL(zip_defn.alias).name

packager_test_defn = Defn('github', 'nebularg/PackagerTest')


ZIPS = {
    'flavoured-toc-only': {
        'toc_files': {
            '_Cata': b'',
        },
        'flavours': {Flavour.Classic},
    },
    'flavoured-and-unflavoured-toc-without-interface-version': {
        'toc_files': {
            '_Cata': b'',
            '': b'',
        },
        'flavours': {Flavour.Classic},
    },
    'flavoured-and-unflavoured-toc-with-interface-version': {
        'toc_files': {
            '_Cata': b'',
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
            f'//api.github.com/repos/{zip_defn.alias}',
            f'//api.github.com/repos/{zip_defn.alias}/releases?per_page=10',
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    'iw_profile_config_values',
    Flavour,
    indirect=True,
)
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_extracting_flavour_from_zip_contents(
    iw_aresponses: aresponses.ResponsesMockServer,
    iw_config_ctx: ConfigBoundCtx,
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
        **Route(
            '//api.github.com',
            path_pattern=re.compile(r'^/repos(/[^/]*){2}/releases/assets/'),
            response=handle_request,
        ).to_aresponses_add_args()
    )

    addon, flavours = package_json_less_addon
    try:
        await github_resolver.resolve_one(zip_defn, None)
    except PkgFilesNotMatching:
        assert iw_config_ctx.config.game_flavour not in flavours
    else:
        assert iw_config_ctx.config.game_flavour in flavours


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_repo_with_release_json_release(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'nebularg/PackagerTest')

    result = await github_resolver.resolve_one(defn, None)
    assert type(result) is Pkg


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_repo_without_releases(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'AdiAddons/AdiBags')

    with pytest.raises(PkgFilesMissing) as exc_info:
        await github_resolver.resolve_one(defn, None)

    assert exc_info.value.message == 'no releases found'


@pytest.mark.usefixtures('_iw_web_client_ctx')
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
            f'//api.github.com/repos/{packager_test_defn.alias}',
            f'//api.github.com/repos/{packager_test_defn.alias}/releases?per_page=10',
        }
    ],
    indirect=True,
)
@pytest.mark.parametrize('any_flavour', [True, None])
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_any_flavour_strategy(
    iw_aresponses: aresponses.ResponsesMockServer,
    iw_config_ctx: ConfigBoundCtx,
    github_resolver: GithubResolver,
    any_flavour: Literal[True, None],
):
    opposite_flavour = next(f for f in Flavour if f is not iw_config_ctx.config.game_flavour)
    opposite_interface = next(
        n for r in opposite_flavour.to_flavour_keyed_enum(FlavourVersionRange).value for n in r
    )

    iw_aresponses.add(
        **Route(
            '//api.github.com',
            path_pattern=re.compile(r'^/repos/nebularg/PackagerTest/releases/assets/'),
            response={
                'releases': [
                    {
                        'filename': 'TestGit-v1.9.7.zip',
                        'nolib': False,
                        'metadata': [
                            {
                                'flavor': opposite_flavour,
                                'interface': opposite_interface,
                            }
                        ],
                    }
                ]
            },
        ).to_aresponses_add_args()
    )
    defn = Defn(
        'github',
        'nebularg/PackagerTest',
        strategies=Strategies({Strategy.AnyFlavour: any_flavour}),
    )

    results = await github_resolver.resolve([defn])
    assert type(results[defn]) is (Pkg if any_flavour else PkgFilesNotMatching)


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_changelog_is_data_url(
    github_resolver: GithubResolver,
):
    defn = Defn('github', 'p3lim-wow/Molinari')

    result = await github_resolver.resolve_one(defn, None)
    assert result.changelog_url.startswith('data:,')


@pytest.mark.parametrize(
    ('iw_profile_config_values', 'flavor', 'interface'),
    [
        (Flavour.Retail, 'mainline', 30400),
        (Flavour.Classic, 'cata', 90207),
        (Flavour.VanillaClassic, 'classic', 90207),
    ],
    indirect=('iw_profile_config_values',),
)
@pytest.mark.parametrize(
    '_iw_mock_aiohttp_requests',
    [
        {
            f'//api.github.com/repos/{packager_test_defn.alias}',
            f'//api.github.com/repos/{packager_test_defn.alias}/releases?per_page=10',
        }
    ],
    indirect=True,
)
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_mismatched_release_is_skipped_and_logged(
    caplog: pytest.LogCaptureFixture,
    iw_aresponses: aresponses.ResponsesMockServer,
    iw_config_ctx: ConfigBoundCtx,
    github_resolver: GithubResolver,
    flavor: str,
    interface: int,
):
    iw_aresponses.add(
        **Route(
            '//api.github.com',
            path_pattern=re.compile(r'^/repos/nebularg/PackagerTest/releases/assets/'),
            response={
                'releases': [
                    {
                        'filename': 'TestGit-v1.9.7.zip',
                        'nolib': False,
                        'metadata': [{'flavor': flavor, 'interface': interface}],
                    }
                ]
            },
        ).to_aresponses_add_args()
    )

    with pytest.raises(PkgFilesNotMatching):
        await github_resolver.resolve_one(packager_test_defn, None)

    assert (
        'instawow._sources.github',
        logging.INFO,
        f'flavor and interface mismatch: {interface} not found in '
        f'{[iw_config_ctx.config.game_flavour.to_flavour_keyed_enum(FlavourVersionRange).value]}',
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
