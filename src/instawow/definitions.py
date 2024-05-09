from __future__ import annotations

from collections.abc import Hashable, Iterable, Iterator, Mapping
from functools import partial
from typing import Literal, overload

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


class Strategies(Mapping[Strategy, object], Hashable):
    initialised = True

    def __init__(self, entries: Mapping[Strategy, object] = {}) -> None:
        self._entries = dict.fromkeys(Strategy) | dict(entries)

    @overload
    def __getitem__(self, key: Literal[Strategy.AnyFlavour], /) -> Literal[True] | None: ...
    @overload
    def __getitem__(self, key: Literal[Strategy.AnyReleaseType], /) -> Literal[True] | None: ...
    @overload
    def __getitem__(self, key: Literal[Strategy.VersionEq], /) -> str | None: ...
    @overload
    def __getitem__(self, key: Strategy, /) -> object: ...
    def __getitem__(self, key: Strategy, /) -> object:
        return self._entries[key]

    def __hash__(self) -> int:
        return hash(frozenset(self._entries.items()))

    def __iter__(self) -> Iterator[Strategy]:
        return iter(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def filled(self) -> dict[Strategy, object]:
        return {s: v for s, v in self._entries.items() if v is not None}


class _UninitialisedStrategies(Strategies):
    initialised = False


_STRATEGY_SEP = ','
_STRATEGY_VALUE_SEP = '='


@fauxfrozen
class Defn:
    source: str
    alias: str
    id: str | None = None
    strategies: Strategies = _UninitialisedStrategies()

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
            make_cls = partial(make_cls, strategies=Strategies())
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
                strategies=Strategies(
                    {
                        Strategy.AnyFlavour: Strategy.AnyFlavour in strategy_values or None,
                        Strategy.AnyReleaseType: Strategy.AnyReleaseType in strategy_values
                        or None,
                        Strategy.VersionEq: strategy_values.get(Strategy.VersionEq),
                    }
                ),
            )

        return make_cls()

    def as_uri(self, *, alias_is_id: bool = False, include_strategies: bool = False) -> str:
        uri = f'{self.source}:{self.id if alias_is_id else self.alias}'

        if include_strategies:
            filled = self.strategies.filled
            if filled:
                uri += f"""#{_STRATEGY_SEP.join(
                    s if v is True else f"{s}={v}" for s, v in filled.items()
                )}"""

        return uri

    def with_default_strategy_set(self) -> Self:
        return attrs.evolve(
            self,
            strategies=Strategies(),
        )

    def with_version(self, version: str) -> Self:
        return attrs.evolve(
            self,
            strategies=Strategies({**self.strategies, Strategy.VersionEq: version}),
        )
