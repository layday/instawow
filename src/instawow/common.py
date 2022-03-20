from __future__ import annotations

from enum import Enum
from typing import TypeVar

from typing_extensions import Protocol

from .utils import StrEnum

_TEnum = TypeVar('_TEnum', bound=Enum)


class _FlavourKeyedEnum(Protocol[_TEnum]):
    retail: _TEnum
    vanilla_classic: _TEnum
    burning_crusade_classic: _TEnum

    def __getitem__(self, __key: str) -> _TEnum:
        ...


class Flavour(StrEnum):
    # The latest Classic version is always aliased to "classic".
    # The logic here is that should Classic not be discontinued
    # it will continue to be updated in place so that new Classic versions
    # will inherit the "_classic_" folder.  This means we won't have to
    # migrate Classic profiles either automatically or by requiring user
    # intervention for new Classic releases.
    retail = 'retail'
    vanilla_classic = 'vanilla_classic'
    burning_crusade_classic = 'classic'

    @classmethod
    def from_flavour_keyed_enum(cls, enum: Enum) -> Flavour:
        return cls[enum.name]

    def to_flavour_keyed_enum(self, enum: _FlavourKeyedEnum[_TEnum]) -> _TEnum:
        return enum[self.name]


class FlavourVersion(Enum):
    retail = (range(1_00_00, 1_13_00), range(2_00_00, 2_05_00), range(3_00_00, 11_00_00))
    vanilla_classic = (range(1_13_00, 2_00_00),)
    burning_crusade_classic = (range(2_05_00, 3_00_00),)

    @classmethod
    def multiple_from_version_string(cls, version_string: str) -> set[FlavourVersion]:
        major, minor, patch = map(int, version_string.split('.'))
        version_number = major * 1_00_00 + minor * 1_00 + patch
        return cls.multiple_from_version_number(version_number)

    @classmethod
    def multiple_from_version_number(cls, version_number: int) -> set[FlavourVersion]:
        return {f for f in cls if f.is_within_version(version_number)}

    def is_within_version(self, version_number: int) -> bool:
        return any(version_number in r for r in self.value)


class Strategy(StrEnum):
    default = 'default'
    latest = 'latest'
    any_flavour = 'any_flavour'
    version = 'version'


class ChangelogFormat(StrEnum):
    html = 'html'
    markdown = 'markdown'
    raw = 'raw'
