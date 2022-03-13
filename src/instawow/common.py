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

    @classmethod
    def to_flavour_keyed_enum(cls, enum: _FlavourKeyedEnum[_TEnum], flavour: Flavour) -> _TEnum:
        return enum[flavour.name]


class FlavourVersion(Enum):
    retail = range(10000, 100000)
    vanilla_classic = range(11300, 20000)
    burning_crusade_classic = range(20500, 30000)

    @classmethod
    def is_within_version(cls, flavour: Flavour, version_number: int) -> bool:
        is_within_version_ = version_number in cls[flavour].value
        if not is_within_version_:
            return False
        elif flavour is Flavour.retail:
            return not any(
                version_number in r.value
                for f, r in cls.__members__.items()
                if f != Flavour.retail
            )
        return True


class Strategy(StrEnum):
    default = 'default'
    latest = 'latest'
    any_flavour = 'any_flavour'
    version = 'version'


class ChangelogFormat(StrEnum):
    html = 'html'
    markdown = 'markdown'
    raw = 'raw'
