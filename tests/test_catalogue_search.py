from __future__ import annotations

import datetime as dt

import pytest

from instawow import pkg_management
from instawow.catalogue.search import search
from instawow.definitions import Defn
from instawow.results import PkgInstalled
from instawow.shared_ctx import ConfigBoundCtx
from instawow.wow_installations import Flavour

pytestmark = pytest.mark.usefixtures('_iw_web_client_ctx')


async def test_basic_search(
    iw_config_ctx: ConfigBoundCtx,
):
    limit = 5
    results = await search(iw_config_ctx, 'molinari', limit=limit)
    assert len(results) <= 5
    assert {('curse', 'molinari'), ('wowi', '13188')} <= {
        (e.source, e.slug or e.id) for e in results
    }


@pytest.mark.parametrize(
    'iw_profile_config_values',
    Flavour,
    indirect=True,
)
async def test_search_flavour_filtering(
    iw_config_ctx: ConfigBoundCtx,
):
    results = await search(iw_config_ctx, 'atlas loot classic', limit=10)
    has_atlas = ('curse', 'atlaslootclassic') in {(e.source, e.slug or e.id) for e in results}
    if iw_config_ctx.config.game_flavour in {
        Flavour.VanillaClassic,
        Flavour.Classic,
    }:
        assert has_atlas
    else:
        assert not has_atlas


async def test_search_source_filtering(
    iw_config_ctx: ConfigBoundCtx,
):
    results = await search(iw_config_ctx, 'molinari', limit=5, sources={'curse'})
    assert all(e.source == 'curse' for e in results)
    assert ('curse', 'molinari') in {(e.source, e.slug) for e in results}


async def test_search_date_filtering(
    iw_config_ctx: ConfigBoundCtx,
):
    start_date = dt.datetime.now(tz=dt.timezone.utc) - dt.timedelta(days=365)
    results = await search(iw_config_ctx, 'molinari', limit=5, start_date=start_date)
    assert all(e.last_updated > start_date for e in results)


async def test_search_unknown_source(
    iw_config_ctx: ConfigBoundCtx,
):
    with pytest.raises(ValueError, match='Unknown source'):
        await search(iw_config_ctx, 'molinari', limit=5, sources={'foo'})


async def test_search_filter_installed(
    iw_config_ctx: ConfigBoundCtx,
):
    results = await search(iw_config_ctx, 'molinari', limit=5, filter_installed='include_only')
    assert not results

    defn = Defn('curse', 'molinari')

    install_result = (await pkg_management.install(iw_config_ctx, [defn], replace_folders=False))[
        defn
    ]
    assert type(install_result) is PkgInstalled

    results = await search(iw_config_ctx, 'molinari', limit=5)
    assert {('curse', 'molinari'), ('github', 'p3lim-wow/molinari')} <= {
        (e.source, e.slug) for e in results
    }

    results = await search(iw_config_ctx, 'molinari', limit=5, filter_installed='include_only')
    assert {('curse', 'molinari'), ('github', 'p3lim-wow/molinari')} & {
        (e.source, e.slug) for e in results
    } == {('curse', 'molinari')}

    results = await search(iw_config_ctx, 'molinari', limit=5, filter_installed='exclude')
    assert {('curse', 'molinari'), ('github', 'p3lim-wow/molinari')} & {
        (e.source, e.slug) for e in results
    } == {('github', 'p3lim-wow/molinari')}

    results = await search(
        iw_config_ctx, 'molinari', limit=5, filter_installed='exclude_from_all_sources'
    )
    assert {('curse', 'molinari'), ('github', 'p3lim-wow/molinari')} & {
        (e.source, e.slug) for e in results
    } == set()


async def test_search_prefer_known_source(
    iw_config_ctx: ConfigBoundCtx,
):
    results = await search(iw_config_ctx, 'molinari', limit=5, prefer_source=None)
    assert {('curse', 'molinari'), ('github', 'p3lim-wow/molinari')} <= {
        (e.source, e.slug) for e in results
    }

    results = await search(iw_config_ctx, 'molinari', limit=5, prefer_source='github')
    assert {('curse', 'molinari'), ('github', 'p3lim-wow/molinari')} & {
        (e.source, e.slug) for e in results
    } == {('github', 'p3lim-wow/molinari')}


async def test_search_prefer_unknown_source(
    iw_config_ctx: ConfigBoundCtx,
):
    with pytest.raises(ValueError, match='Unknown preferred source: foo'):
        await search(iw_config_ctx, 'molinari', limit=5, prefer_source='foo')
