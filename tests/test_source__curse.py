from __future__ import annotations

import re

import pytest
from yarl import URL

from instawow import config_ctx, pkg_management
from instawow._sources.cfcore import CfCoreResolver
from instawow.definitions import Defn, Strategies, Strategy
from instawow.results import PkgFilesNotMatching
from instawow.wow_installations import Flavour

pytestmark = pytest.mark.usefixtures('_iw_config_ctx', '_iw_web_client_ctx')


CURSE_IDS = {
    'big-wigs': '2382',
    'molinari': '20338',
    'adibags': '23350',
    'mythic-dungeon-tools': '288981',
    'masque': '13592',
    'elkbuffbars': '2398',
    'atlaslootclassic': '326516',
    'elvui-adibags': '333072',
    'bigwigs-voice-korean': '402180',
    'dialogueui': '989270',
}


@pytest.fixture
def curse_resolver():
    return CfCoreResolver()


@pytest.mark.parametrize(
    'iw_profile_config_values',
    Flavour.iter_supported(),
    indirect=True,
)
async def test_resolve_flavourful_addon(
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', CURSE_IDS['masque'])

    result = (await curse_resolver.resolve([defn]))[defn]
    assert type(result) is dict


@pytest.mark.parametrize(
    'iw_profile_config_values',
    Flavour.iter_supported(),
    indirect=True,
)
async def test_resolve_classic_only_addon(
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', CURSE_IDS['atlaslootclassic'])

    result = (await curse_resolver.resolve([defn]))[defn]

    match config_ctx.config().game_flavour:
        case Flavour.VanillaClassic:
            assert type(result) is dict
        case _:
            assert type(result) is PkgFilesNotMatching
            assert (
                str(result)
                == f'no files found for: {Strategy.AnyFlavour}=None; {Strategy.AnyReleaseType}=None; {Strategy.VersionEq}=None'
            )


async def test_curse_any_flavour_strategy(
    curse_resolver: CfCoreResolver,
):
    flavourful = Defn(
        'curse', CURSE_IDS['masque'], strategies=Strategies({Strategy.AnyFlavour: True})
    )
    classics_only = Defn(
        'curse', CURSE_IDS['atlaslootclassic'], strategies=Strategies({Strategy.AnyFlavour: True})
    )

    results = await curse_resolver.resolve([flavourful, classics_only])
    assert all(type(r) is dict for r in results.values())


async def test_curse_slug_match(
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', 'molinari')

    result = (await curse_resolver.resolve([defn]))[defn]
    assert type(result) is dict
    assert result['id'] == CURSE_IDS['molinari']


@pytest.mark.parametrize(
    'version', ['100005.97-Release', '100005.97-Release_4419396', 'foo_4419396']
)
async def test_curse_version_pinning(
    curse_resolver: CfCoreResolver,
    version: str,
):
    defn = Defn('curse', 'molinari', strategies=Strategies({Strategy.VersionEq: version}))

    result = (await curse_resolver.resolve([defn]))[defn]
    assert type(result) is dict
    assert result['version'] == '100005.97-Release_4419396'


async def test_curse_deps_retrieved():
    defn = Defn('curse', CURSE_IDS['bigwigs-voice-korean'])

    results = await pkg_management.resolve([defn], with_deps=True)
    pkg_candidates, errors = pkg_management.split_results(results.items())
    assert not errors
    assert {'bigwigs-voice-korean', 'big-wigs'} == {p['slug'] for p in pkg_candidates.values()}


async def test_curse_no_stable_release_falls_back_on_pre(
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', CURSE_IDS['dialogueui'])

    result = (await curse_resolver.resolve([defn]))[defn]
    assert type(result) is dict


async def test_changelog_url_format(
    curse_resolver: CfCoreResolver,
):
    defn = Defn('curse', CURSE_IDS['masque'])

    result = (await curse_resolver.resolve([defn]))[defn]
    assert type(result) is dict
    assert re.match(
        r'https://api\.curseforge\.com/v1/mods/\d+/files/\d+/changelog',
        result['changelog_url'],
    )


@pytest.mark.parametrize(
    ('url', 'extracted_alias'),
    [
        (
            'https://www.curseforge.com/wow/addons/molinari',
            'molinari',
        ),
        (
            'https://www.curseforge.com/wow/addons/molinari/download',
            'molinari',
        ),
    ],
)
def test_can_extract_alias_from_url(
    curse_resolver: CfCoreResolver,
    url: str,
    extracted_alias: str,
):
    assert curse_resolver.get_alias_from_url(URL(url)) == extracted_alias
