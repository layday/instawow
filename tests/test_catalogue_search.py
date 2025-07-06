from __future__ import annotations

import datetime as dt

import pytest

from instawow import config_ctx, pkg_management
from instawow.catalogue.search import search
from instawow.definitions import Defn
from instawow.results import PkgInstalled
from instawow.wow_installations import Track

pytestmark = pytest.mark.usefixtures('_iw_config_ctx', '_iw_web_client_ctx')


async def test_basic_search():
    limit = 5
    results = await search('masque', limit=limit)
    assert len(results) <= 5
    assert {('curse', 'masque'), ('wowi', '12097')} <= {
        (e.source, e.slug or e.id) for e in results
    }


@pytest.mark.parametrize(
    'iw_profile_config_values',
    Track,
    indirect=True,
)
async def test_search_flavour_filtering():
    results = await search('atlas loot classic', limit=10)
    has_atlas = ('curse', 'atlaslootclassic') in {(e.source, e.slug or e.id) for e in results}
    assert has_atlas == (config_ctx.config().track is Track.VanillaClassic)


async def test_search_source_filtering():
    results = await search('masque', limit=5, sources={'curse'})
    assert all(e.source == 'curse' for e in results)
    assert ('curse', 'masque') in {(e.source, e.slug) for e in results}


async def test_search_date_filtering():
    start_date = dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=365)
    results = await search('masque', limit=5, start_date=start_date)
    assert all(e.last_updated > start_date for e in results)


async def test_search_unknown_source():
    with pytest.raises(ValueError, match='Unknown source'):
        await search('masque', limit=5, sources={'foo'})


async def test_search_filter_installed():
    results = await search('masque', limit=5, filter_installed='include_only')
    assert not results

    defn = Defn('curse', 'masque')

    install_result = (await pkg_management.install([defn], replace_folders=False))[defn]
    assert type(install_result) is PkgInstalled

    results = await search('masque', limit=5)
    assert {('curse', 'masque'), ('github', 'sfx-wow/masque')} <= {
        (e.source, e.slug) for e in results
    }

    results = await search('masque', limit=5, filter_installed='include_only')
    assert {('curse', 'masque'), ('github', 'sfx-wow/masque')} & {
        (e.source, e.slug) for e in results
    } == {('curse', 'masque')}

    results = await search('masque', limit=5, filter_installed='exclude')
    assert {('curse', 'masque'), ('github', 'sfx-wow/masque')} & {
        (e.source, e.slug) for e in results
    } == {('github', 'sfx-wow/masque')}

    results = await search('masque', limit=5, filter_installed='exclude_from_all_sources')
    assert {('curse', 'masque'), ('github', 'sfx-wow/masque')} & {
        (e.source, e.slug) for e in results
    } == set()


async def test_search_prefer_known_source():
    results = await search('masque', limit=5, prefer_source=None)
    assert {('curse', 'masque'), ('github', 'sfx-wow/masque')} <= {
        (e.source, e.slug) for e in results
    }

    results = await search('masque', limit=5, prefer_source='github')
    assert {('curse', 'masque'), ('github', 'sfx-wow/masque')} & {
        (e.source, e.slug) for e in results
    } == {('github', 'sfx-wow/masque')}


async def test_search_prefer_unknown_source():
    with pytest.raises(ValueError, match='Unknown preferred source: foo'):
        await search('masque', limit=5, prefer_source='foo')
