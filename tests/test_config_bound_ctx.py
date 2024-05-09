from __future__ import annotations

import pytest

from instawow._sources import DEFAULT_RESOLVERS
from instawow.shared_ctx import ConfigBoundCtx


def test_auth_bound_resolvers_are_not_unloaded_if_tokens_set(
    iw_config_ctx: ConfigBoundCtx,
):
    assert {
        r.metadata.id for r in DEFAULT_RESOLVERS if r.requires_access_token is not None
    }.issubset(iw_config_ctx.resolvers)


@pytest.mark.parametrize(
    'iw_global_config_values',
    [None],
    indirect=True,
)
def test_auth_bound_resolvers_are_unloaded_if_tokens_unset(
    iw_config_ctx: ConfigBoundCtx,
):
    assert {
        r.metadata.id for r in DEFAULT_RESOLVERS if r.requires_access_token is not None
    }.isdisjoint(iw_config_ctx.resolvers)
