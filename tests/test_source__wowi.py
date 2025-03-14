from __future__ import annotations

import pytest
from yarl import URL

from instawow._sources.wowi import WowiResolver
from instawow.definitions import Defn

pytestmark = pytest.mark.usefixtures('_iw_config_ctx', '_iw_web_client_ctx')


@pytest.fixture
def wowi_resolver():
    return WowiResolver()


async def test_resolve_addon(
    wowi_resolver: WowiResolver,
):
    defn = Defn('wowi', '13188-molinari')

    result = (await wowi_resolver.resolve([defn]))[defn]
    assert type(result) is dict


async def test_changelog_url_format(
    wowi_resolver: WowiResolver,
):
    defn = Defn('wowi', '13188-molinari')

    result = (await wowi_resolver.resolve([defn]))[defn]
    assert type(result) is dict
    assert result['changelog_url'].startswith('data:,')


@pytest.mark.parametrize(
    ('url', 'extracted_alias'),
    [
        (
            'https://www.wowinterface.com/downloads/landing.php?fileid=13188',
            '13188',
        ),
        (
            'https://wowinterface.com/downloads/landing.php?fileid=13188',
            '13188',
        ),
        (
            'https://www.wowinterface.com/downloads/fileinfo.php?id=13188',
            '13188',
        ),
        (
            'https://wowinterface.com/downloads/fileinfo.php?id=13188',
            '13188',
        ),
        (
            'https://www.wowinterface.com/downloads/download13188-Molinari',
            '13188',
        ),
        (
            'https://wowinterface.com/downloads/download13188-Molinari',
            '13188',
        ),
        (
            'https://www.wowinterface.com/downloads/info13188-Molinari.html',
            '13188',
        ),
        (
            'https://wowinterface.com/downloads/info13188-Molinari.html',
            '13188',
        ),
        (
            'https://www.wowinterface.com/downloads/info13188',
            '13188',
        ),
        (
            'https://wowinterface.com/downloads/info13188',
            '13188',
        ),
    ],
)
def test_can_extract_alias_from_url(
    wowi_resolver: WowiResolver,
    url: str,
    extracted_alias: str,
):
    assert wowi_resolver.get_alias_from_url(URL(url)) == extracted_alias
