from __future__ import annotations

from contextlib import nullcontext

import pytest

from instawow import config_ctx
from instawow._sources.tukui import TukuiResolver
from instawow.definitions import Defn
from instawow.results import PkgFilesNotMatching
from instawow.wow_installations import Flavour

pytestmark = pytest.mark.usefixtures('_iw_config_ctx', '_iw_web_client_ctx')


@pytest.fixture
def tukui_resolver():
    return TukuiResolver()


@pytest.mark.parametrize(
    'iw_profile_config_values',
    Flavour.iter_supported(),
    indirect=True,
)
@pytest.mark.parametrize('alias', ['tukui', 'elvui'])
async def test_resolve_addon(
    tukui_resolver: TukuiResolver,
    alias: str,
):
    defn = Defn('tukui', alias)

    with (
        pytest.raises(PkgFilesNotMatching)
        if (alias == 'tukui' and config_ctx.config().game_flavour is Flavour.Classic)
        else nullcontext()
    ):
        result = await tukui_resolver.resolve_one(defn, None)

        assert type(result) is dict
        assert result['slug'] == alias


async def test_changelog_url_format(
    tukui_resolver: TukuiResolver,
):
    defn = Defn('tukui', 'tukui')

    result = await tukui_resolver.resolve_one(defn, None)

    assert result['changelog_url'] == 'https://api.tukui.org/v1/changelog/tukui#20.41'
