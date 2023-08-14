from __future__ import annotations

import pytest

from instawow._sources.tukui import TukuiResolver
from instawow.common import Defn, Flavour
from instawow.manager_ctx import ManagerCtx
from instawow.pkg_models import Pkg


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
    tukui_resolver: TukuiResolver,
    alias: str,
):
    defn = Defn('tukui', alias)

    result = await tukui_resolver.resolve_one(defn, None)

    assert type(result) is Pkg
    assert result.slug == alias


async def test_changelog_url_format(
    tukui_resolver: TukuiResolver,
):
    defn = Defn('tukui', 'tukui')

    result = await tukui_resolver.resolve_one(defn, None)

    assert result.changelog_url == 'https://api.tukui.org/v1/changelog/tukui#20.38'
