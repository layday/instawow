from __future__ import annotations

from typing import Any

from instawow.common import ChangelogFormat, Defn, SourceMetadata, Strategy, StrategyValues
from instawow.manager_ctx import ManagerCtx
from instawow.resolvers import BaseResolver
from instawow.results import PkgStrategiesUnsupported


async def test_unsupported_strategies_raise(
    iw_manager_ctx: ManagerCtx,
):
    class Resolver(BaseResolver):
        metadata = SourceMetadata(
            id='foo',
            name='Foo',
            strategies=frozenset(),
            changelog_format=ChangelogFormat.Raw,
            addon_toc_key=None,
        )

        def resolve_one(self, defn: Defn, metadata: Any):
            raise NotImplementedError

    defn = Defn(
        Resolver.metadata.id,
        'foo',
        strategies=StrategyValues(
            any_flavour=True,
            any_release_type=True,
            version_eq='0',
        ),
    )

    result = (await Resolver(iw_manager_ctx).resolve([defn]))[defn]

    assert type(result) is PkgStrategiesUnsupported
    assert (
        result.message
        == f'strategies are not valid for source: {Strategy.AnyFlavour}, {Strategy.AnyReleaseType}, {Strategy.VersionEq}'
    )
