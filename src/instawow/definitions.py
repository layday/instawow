from __future__ import annotations

from collections.abc import Iterable
from functools import partial
from typing import Literal

import attrs
from typing_extensions import Self
from yarl import URL

from ._utils.compat import StrEnum, fauxfrozen


class Strategy(StrEnum):
    AnyFlavour = 'any_flavour'
    AnyReleaseType = 'any_release_type'
    VersionEq = 'version_eq'


class ChangelogFormat(StrEnum):
    Html = 'html'
    Markdown = 'markdown'
    Raw = 'raw'


@fauxfrozen
class SourceMetadata:
    id: str
    name: str
    strategies: frozenset[Strategy]
    changelog_format: ChangelogFormat
    addon_toc_key: str | None


@fauxfrozen
class StrategyValues:
    any_flavour: Literal[True, None] = None
    any_release_type: Literal[True, None] = None
    version_eq: str | None = None

    initialised = True

    @property
    def filled_strategies(self) -> dict[Strategy, object]:
        return {Strategy(p): v for p, v in attrs.asdict(self).items() if v is not None}


@fauxfrozen
class _UninitialisedStrategyValues(StrategyValues):
    initialised = False


_STRATEGY_SEP = ','
_STRATEGY_VALUE_SEP = '='


@fauxfrozen
class Defn:
    source: str
    alias: str
    id: str | None = None
    strategies: StrategyValues = _UninitialisedStrategyValues()

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        known_sources: Iterable[str],
        allow_unsourced: bool,
    ) -> Self:
        """Construct a ``Defn`` from a URI."""
        url = URL(uri)

        if url.scheme not in known_sources:
            if not allow_unsourced:
                raise ValueError(f'Unable to extract source from {uri}')

            make_cls = partial(cls, source='', alias=uri)
        else:
            make_cls = partial(cls, source=url.scheme, alias=url.path)

        if url.fragment == _STRATEGY_VALUE_SEP:
            make_cls = partial(make_cls, strategies=StrategyValues())
        elif url.fragment:
            strategy_values = {
                s: v
                for f in url.fragment.split(_STRATEGY_SEP)
                for s, _, v in (f.partition(_STRATEGY_VALUE_SEP),)
                if s
            }

            unknown_strategies = strategy_values.keys() - set(Strategy)
            if unknown_strategies:
                raise ValueError(f'Unknown strategies: {", ".join(unknown_strategies)}')

            make_cls = partial(
                make_cls,
                strategies=StrategyValues(
                    any_flavour=Strategy.AnyFlavour in strategy_values or None,
                    any_release_type=Strategy.AnyReleaseType in strategy_values or None,
                    version_eq=strategy_values.get(Strategy.VersionEq),
                ),
            )

        return make_cls()

    def as_uri(self, include_strategies: bool = False) -> str:
        uri = f'{self.source}:{self.alias}'

        if include_strategies:
            filled_strategies = self.strategies.filled_strategies
            if filled_strategies:
                uri += f"""#{_STRATEGY_SEP.join(
                    s if v is True else f"{s}={v}" for s, v in filled_strategies.items()
                )}"""

        return uri

    def with_default_strategy_set(self) -> Self:
        return attrs.evolve(
            self,
            strategies=StrategyValues(),
        )

    def with_version(self, version: str) -> Self:
        return attrs.evolve(
            self,
            strategies=StrategyValues(**(attrs.asdict(self.strategies) | {'version_eq': version})),
        )
