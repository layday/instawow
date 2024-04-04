from __future__ import annotations

from contextlib import nullcontext

import pytest

from instawow._sources.tukui import TukuiResolver
from instawow.definitions import Defn
from instawow.manager_ctx import ManagerCtx
from instawow.pkg_models import Pkg
from instawow.results import PkgFilesNotMatching
from instawow.wow_installations import Flavour


@pytest.fixture
def tukui_resolver(
    iw_manager_ctx: ManagerCtx,
):
    return TukuiResolver(iw_manager_ctx)


@pytest.mark.parametrize(
    'iw_config_values',
    Flavour,
    indirect=True,
)
@pytest.mark.parametrize('alias', ['tukui', 'elvui'])
async def test_resolve_addon(
    iw_manager_ctx: ManagerCtx,
    tukui_resolver: TukuiResolver,
    alias: str,
):
    defn = Defn('tukui', alias)

    with (
        pytest.raises(PkgFilesNotMatching)
        if iw_manager_ctx.config.game_flavour is Flavour.CataclysmClassic
        else nullcontext()
    ):
        result = await tukui_resolver.resolve_one(defn, None)

        assert type(result) is Pkg
        assert result.slug == alias


async def test_changelog_url_format(
    tukui_resolver: TukuiResolver,
):
    defn = Defn('tukui', 'tukui')

    result = await tukui_resolver.resolve_one(defn, None)

    assert result.changelog_url == 'https://api.tukui.org/v1/changelog/tukui#20.41'
