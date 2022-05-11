from __future__ import annotations

from enum import Enum
import os
from pathlib import PurePath
import typing
from typing import TypeVar

from attrs import frozen
from typing_extensions import Protocol, Self

from .utils import StrEnum, fill

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
    def from_flavour_keyed_enum(cls, enum: Enum) -> Self:
        return cls[enum.name]

    def to_flavour_keyed_enum(self, enum: _FlavourKeyedEnum[_TEnum]) -> _TEnum:
        return enum[self.name]


class FlavourVersion(Enum):
    retail = (range(1_00_00, 1_13_00), range(2_00_00, 2_05_00), range(3_00_00, 11_00_00))
    vanilla_classic = (range(1_13_00, 2_00_00),)
    burning_crusade_classic = (range(2_05_00, 3_00_00),)

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
    elif tail[0] in {'_classic_era_', '_classic_era_beta_', '_classic_era_ptr_'}:
        return Flavour.vanilla_classic
    elif tail[0] in {'_classic_', '_classic_beta_', '_classic_ptr_'}:
        return Flavour.burning_crusade_classic
    else:
        return Flavour.retail


class Strategy(StrEnum):
    default = 'default'
    latest = 'latest'
    any_flavour = 'any_flavour'
    version = 'version'


class ChangelogFormat(StrEnum):
    html = 'html'
    markdown = 'markdown'
    raw = 'raw'


@frozen
class SourceMetadata:
    id: str
    name: str
    strategies: typing.FrozenSet[Strategy]
    changelog_format: ChangelogFormat
