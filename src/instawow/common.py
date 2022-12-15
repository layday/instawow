from __future__ import annotations

import enum
import os
import typing
from pathlib import PurePath
from typing import Literal, Protocol, TypeVar

from attrs import asdict, evolve, frozen
from typing_extensions import Self

from .utils import StrEnum, fill

_TEnum = TypeVar('_TEnum', bound=enum.Enum)


class _FlavourKeyedEnum(Protocol[_TEnum]):
    retail: _TEnum
    vanilla_classic: _TEnum
    classic: _TEnum

    def __getitem__(self, __key: str) -> _TEnum:
        ...


class Flavour(StrEnum):
    # The latest Classic version is always aliased to "classic".
    # The logic here is that should Classic not be discontinued
    # it will continue to be updated in place so that new Classic versions
    # will inherit the "_classic_" folder.  This means we won't have to
    # migrate Classic profiles either automatically or by requiring user
    # intervention for new Classic releases.
    retail = enum.auto()
    vanilla_classic = enum.auto()
    classic = enum.auto()

    @classmethod
    def from_flavour_keyed_enum(cls, flavour_keyed_enum: enum.Enum) -> Self:
        return cls[flavour_keyed_enum.name]

    def to_flavour_keyed_enum(self, flavour_keyed_enum: _FlavourKeyedEnum[_TEnum]) -> _TEnum:
        return flavour_keyed_enum[self.name]


class FlavourVersionRange(enum.Enum):
    retail = (
        range(1_00_00, 1_13_00), range(2_00_00, 2_05_00), range(3_00_00, 3_04_00), range(4_00_00, 11_00_00)  # fmt: skip
    )
    vanilla_classic = (range(1_13_00, 2_00_00),)
    classic = (range(3_04_00, 4_00_00),)

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


def infer_flavour_from_path(path: os.PathLike[str] | str) -> Flavour:
    tail = tuple(map(str.casefold, PurePath(path).parts[-3:]))
    if len(tail) != 3 or tail[1:] != ('interface', 'addons'):
        return Flavour.retail

    flavour_dir = tail[0]
    if flavour_dir in {'_classic_era_', '_classic_era_beta_', '_classic_era_ptr_'}:
        return Flavour.vanilla_classic
    elif flavour_dir in {'_classic_', '_classic_beta_', '_classic_ptr_'}:
        return Flavour.classic
    else:
        return Flavour.retail


class Strategy(StrEnum):
    any_flavour = enum.auto()
    any_release_type = enum.auto()
    version_eq = enum.auto()


class ChangelogFormat(StrEnum):
    html = enum.auto()
    markdown = enum.auto()
    raw = enum.auto()


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
    version_eq: typing.Union[str, None] = None

    @property
    def filled_strategies(self) -> frozenset[Strategy]:
        return frozenset(Strategy(p) for p, v in asdict(self).items() if v is not None)


@frozen(hash=True)
class Defn:
    source: str
    alias: str
    id: typing.Union[str, None] = None
    strategies: StrategyValues = StrategyValues()

    def with_version(self, version: str) -> Self:
        return evolve(self, strategies=evolve(self.strategies, version_eq=version))


class AddonHashMethod(enum.Enum):
    wowup = enum.auto()
