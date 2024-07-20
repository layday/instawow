from __future__ import annotations

from typing import Any

import pytest

from instawow.definitions import ChangelogFormat, Defn, SourceMetadata, Strategies, Strategy
from instawow.resolvers import BaseResolver
from instawow.results import PkgStrategiesUnsupported
from instawow.shared_ctx import ConfigBoundCtx


@pytest.mark.parametrize(
    ('iw_global_config_values', 'disabled_reason'),
    [('foo', None), (None, 'access token is not configured')],
    indirect=('iw_global_config_values',),
)
def test_disabled_reason_forwarded(
    iw_config_ctx: ConfigBoundCtx,
    disabled_reason: str | None,
):
    assert (
        next((d for d in iw_config_ctx.resolvers.disabled_resolver_reasons.values()), None)
        == disabled_reason
    )


async def test_unsupported_strategies_raise(
    iw_config_ctx: ConfigBoundCtx,
):
    class Resolver(BaseResolver):
        metadata = SourceMetadata(
            id='foo',
            name='Foo',
            strategies=frozenset(),
            changelog_format=ChangelogFormat.Raw,
            addon_toc_key=None,
        )

        def _resolve_one(self, defn: Defn, metadata: Any):
            raise NotImplementedError

    defn = Defn(
        Resolver.metadata.id,
        'foo',
        strategies=Strategies(
            {
                Strategy.AnyFlavour: True,
                Strategy.AnyReleaseType: True,
                Strategy.VersionEq: '0',
            }
        ),
    )

    result = (await Resolver(iw_config_ctx.config).resolve([defn]))[defn]

    assert type(result) is PkgStrategiesUnsupported
    assert (
        result.message
        == f'strategies are not valid for source: {Strategy.AnyFlavour}, {Strategy.AnyReleaseType}, {Strategy.VersionEq}'
    )
