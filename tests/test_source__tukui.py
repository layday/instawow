from __future__ import annotations

from contextlib import nullcontext

import pytest

from instawow._sources.tukui import TukuiResolver
from instawow.definitions import Defn
from instawow.pkg_models import Pkg
from instawow.results import PkgFilesNotMatching
from instawow.shared_ctx import ConfigBoundCtx
from instawow.wow_installations import Flavour


@pytest.fixture
def tukui_resolver(
    iw_config_ctx: ConfigBoundCtx,
):
    return TukuiResolver(iw_config_ctx.config)


@pytest.mark.parametrize(
    'iw_profile_config_values',
    Flavour,
    indirect=True,
)
@pytest.mark.parametrize('alias', ['tukui', 'elvui'])
@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_resolve_addon(
    iw_config_ctx: ConfigBoundCtx,
    tukui_resolver: TukuiResolver,
    alias: str,
):
    defn = Defn('tukui', alias)

    with (
        pytest.raises(PkgFilesNotMatching)
        if (alias == 'tukui' and iw_config_ctx.config.game_flavour is Flavour.Classic)
        or (alias == 'elvui' and iw_config_ctx.config.game_flavour is Flavour.WrathClassic)
        else nullcontext()
    ):
        result = await tukui_resolver.resolve_one(defn, None)

        assert type(result) is Pkg
        assert result.slug == alias


@pytest.mark.usefixtures('_iw_web_client_ctx')
async def test_changelog_url_format(
    tukui_resolver: TukuiResolver,
):
    defn = Defn('tukui', 'tukui')

    result = await tukui_resolver.resolve_one(defn, None)

    assert result.changelog_url == 'https://api.tukui.org/v1/changelog/tukui#20.41'
