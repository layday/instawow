from __future__ import annotations

import enum
from collections.abc import Iterable
from functools import partial
from typing import Literal, Protocol, TypeVar

from attrs import asdict, evolve, frozen
from typing_extensions import Self
from yarl import URL

from .utils import StrEnum, fill

_TEnum = TypeVar('_TEnum', bound=enum.Enum)


class _FlavourKeyedEnumMeta(type(Protocol)):  # pragma: no cover
    def __getitem__(self: type[_FlavourKeyedEnum[_TEnum]], __key: str) -> _TEnum:
        ...


class _FlavourKeyedEnum(Protocol[_TEnum], metaclass=_FlavourKeyedEnumMeta):  # pragma: no cover
    Retail: _TEnum
    VanillaClassic: _TEnum
    Classic: _TEnum


class Flavour(StrEnum):
    # The latest Classic version is always aliased to "classic".
    # The logic here is that should Classic not be discontinued
    # it will continue to be updated in place so that new Classic versions
    # will inherit the "_classic_" folder.  This means we won't have to
    # migrate Classic profiles either automatically or by requiring user
    # intervention for new Classic releases.
    Retail = 'retail'
    VanillaClassic = 'vanilla_classic'
    Classic = 'classic'

    @classmethod
    def from_flavour_keyed_enum(cls, flavour_keyed_enum: enum.Enum) -> Self:
        return cls[flavour_keyed_enum.name]

    def to_flavour_keyed_enum(self, flavour_keyed_enum: type[_FlavourKeyedEnum[_TEnum]]) -> _TEnum:
        return flavour_keyed_enum[self.name]


class FlavourVersionRange(enum.Enum):
    Retail = (
        range(1_00_00, 1_13_00),
        range(2_00_00, 2_05_00),
        range(3_00_00, 3_04_00),
        range(4_00_00, 11_00_00),
    )
    VanillaClassic = (range(1_13_00, 2_00_00),)
    Classic = (range(3_04_00, 4_00_00),)

    @classmethod
    def from_version_string(cls, version_string: str) -> Self | None:
        major, minor, patch = fill(map(int, version_string.split('.')), 0, 3)
        version_number = major * 1_00_00 + minor * 1_00 + patch
        return cls.from_version_number(version_number)

    @classmethod
    def from_version_number(cls, version_number: int) -> Self | None:
        return next((f for f in cls if f.is_within_version(version_number)), None)

    def is_within_version(self, version_number: int) -> bool:
        return any(version_number in r for r in self.value)


class Strategy(StrEnum):
    AnyFlavour = 'any_flavour'
    AnyReleaseType = 'any_release_type'
    VersionEq = 'version_eq'


class ChangelogFormat(StrEnum):
    Html = 'html'
    Markdown = 'markdown'
    Raw = 'raw'


@frozen
class SourceMetadata:
    id: str
    name: str
    strategies: frozenset[Strategy]
    changelog_format: ChangelogFormat
    addon_toc_key: str | None


@frozen
class StrategyValues:
    any_flavour: Literal[True, None] = None
    any_release_type: Literal[True, None] = None
    version_eq: str | None = None

    @property
    def filled_strategies(self) -> dict[Strategy, object]:
        return {Strategy(p): v for p, v in asdict(self).items() if v is not None}


_UNSOURCE = '*'
_UNSOURCE_NAME = 'ASTERISK'  # unicodedata.name(_UNSOURCE)

_STRATEGY_SEP = ','


@frozen(hash=True)
class Defn:
    source: str
    alias: str
    id: str | None = None
    strategies: StrategyValues = StrategyValues()

    @classmethod
    def from_uri(
        cls,
        uri: str,
        *,
        known_sources: Iterable[str],
        allow_unsourced: bool,
        include_strategies: bool = False,
    ) -> Self:
        """Construct a ``Defn`` from a URI."""
        url = URL(uri)

        if url.scheme not in known_sources:
            if not allow_unsourced:
                raise ValueError(f'Unable to extract source from {uri}')
            elif url.scheme == _UNSOURCE:
                raise ValueError(f'{_UNSOURCE} ({_UNSOURCE_NAME}) is not valid as a source')

            make_cls = partial(cls, source=_UNSOURCE, alias=uri)
        else:
            make_cls = partial(cls, source=url.scheme, alias=url.path)

        if include_strategies:
            strategy_values = {
                s: v
                for f in url.fragment.split(_STRATEGY_SEP)
                for s, _, v in (f.partition('='),)
                if s
            }
            if strategy_values:
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

    def with_version(self, version: str) -> Self:
        return evolve(self, strategies=evolve(self.strategies, version_eq=version))

    @property
    def is_unsourced(self) -> bool:
        return self.source == _UNSOURCE


class AddonHashMethod(enum.Enum):
    Wowup = enum.auto()
