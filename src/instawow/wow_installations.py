from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from enum import Enum
from functools import cache
from pathlib import Path
from typing import TypedDict, TypeVar

from typing_extensions import NotRequired, Self

from ._utils.compat import StrEnum
from ._utils.iteration import fill

_TEnum = TypeVar('_TEnum', bound=Enum)


class _FlavourMeta(TypedDict):
    aliases: NotRequired[list[str]]
    is_retired: NotRequired[bool]


_DummyFlavourMeta = _FlavourMeta()


class Flavour(StrEnum):
    # The current Classic version is always aliased to "classic".
    # The assumption here is that should Classic not be discontinued
    # it will continue to be updated in place so that new Classic versions
    # will inherit the "_classic_" folder.  This means we won't have to
    # migrate Classic profiles either automatically or by requiring user
    # intervention for new Classic releases.
    Retail = ('retail',)
    VanillaClassic = ('vanilla_classic',)
    Classic = ('classic', _FlavourMeta(aliases=['cataclysm_classic']))
    WrathClassic = ('wrath_classic', _FlavourMeta(is_retired=True))

    is_retired: bool

    def __new__(cls, value: str, flavour_meta: _FlavourMeta = _DummyFlavourMeta) -> Self:
        self = str.__new__(cls, value)
        self._value_ = value
        for alias in flavour_meta.get('aliases', []):
            cls._value2member_map_.setdefault(alias, self)
        self.is_retired = flavour_meta.get('is_retired', False)
        return self

    @classmethod
    def from_flavour_keyed_enum(cls, flavour_keyed_enum: Enum) -> Self:
        return cls[flavour_keyed_enum.name]

    def to_flavour_keyed_enum(self, flavour_keyed_enum: type[_TEnum]) -> _TEnum:
        return flavour_keyed_enum[self.name]

    def get_flavour_groups(self, affine: bool) -> list[tuple[Flavour, ...] | None]:
        match (self, affine):
            case (self.__class__.Classic, True):
                return [(self, self.__class__.WrathClassic), None]
            case (_, True):
                return [(self,), None]
            case _:
                return [(self,)]


class FlavourVersionRange(Enum):
    Retail = (
        range(1_00_00, 1_13_00),
        range(2_00_00, 2_05_00),
        range(3_00_00, 3_04_00),
        range(4_00_00, 4_04_00),
        range(5_00_00, 12_00_00),
    )
    VanillaClassic = (range(1_13_00, 2_00_00),)
    Classic = (range(4_04_00, 5_00_00),)
    WrathClassic = (range(3_04_00, 4_00_00),)

    @classmethod
    def _parse_version_string(cls, version_string: str) -> int:
        major, minor, patch = fill(map(int, version_string.split('.')), 0, 3)
        return major * 1_00_00 + minor * 1_00 + patch

    @classmethod
    def from_version(cls, version: int | str) -> Self | None:
        version_number = (
            version if isinstance(version, int) else cls._parse_version_string(version)
        )
        return next((f for f in cls if f.contains(version_number)), None)

    def contains(self, version: int | str) -> bool:
        version_number = (
            version if isinstance(version, int) else self._parse_version_string(version)
        )
        return any(version_number in r for r in self.value)


class _Product(TypedDict):
    code: str
    flavour: Flavour


_DELECTABLE_DIR_NAMES: dict[str, _Product] = {
    '_retail_': {
        'code': 'wow',
        'flavour': Flavour.Retail,
    },
    '_ptr_': {
        'code': 'wowt',
        'flavour': Flavour.Retail,
    },
    '_xptr_': {
        'code': 'wowxptr',
        'flavour': Flavour.Retail,
    },
    '_beta_': {
        'code': 'wow_beta',
        'flavour': Flavour.Retail,
    },
    '_classic_era_': {
        'code': 'wow_classic_era',
        'flavour': Flavour.VanillaClassic,
    },
    '_classic_era_ptr_': {
        'code': 'wow_classic_era_ptr',
        'flavour': Flavour.VanillaClassic,
    },
    # '_classic_era_beta_': {
    #     'code': 'wow_classic_era_beta',
    #     'flavour': Flavour.VanillaClassic,
    # },
    '_classic_': {
        'code': 'wow_classic',
        'flavour': Flavour.Classic,
    },
    '_classic_ptr_': {
        'code': 'wow_classic_ptr',
        'flavour': Flavour.Classic,
    },
    '_classic_beta_': {
        'code': 'wow_classic_beta',
        'flavour': Flavour.Classic,
    },
}

ADDON_DIR_PARTS = ('Interface', 'AddOns')
_NORMALISED_ADDON_DIR_PARTS = tuple(map(str.casefold, ADDON_DIR_PARTS))


def _find_mac_installations():
    import subprocess

    try:
        possible_installations = subprocess.check_output(
            [
                'mdfind',
                "kMDItemCFBundleIdentifier == 'com.blizzard.worldofwarcraft'",
            ],
            text=True,
            timeout=3,
        ).splitlines()
    except subprocess.TimeoutExpired:
        pass
    else:
        for match in possible_installations:
            installation_path = Path(match).parent
            yield (installation_path, _DELECTABLE_DIR_NAMES.get(installation_path.name))


def find_installations() -> Iterator[tuple[Path, _Product | None]]:
    if sys.platform == 'darwin':
        yield from _find_mac_installations()


def _read_info(info_path: Path):
    with open(info_path, encoding='utf-8') as info:
        header = next(info)
        fields = tuple(f[: f.find('!')] for f in header.rstrip().split('|'))
        return [dict(zip(fields, e.rstrip().split('|'))) for e in info if not e.startswith('#')]


@cache
def _get_installed_versions(outer_installation_path: Path):
    return {
        e['Product']: e['Version'] for e in _read_info(outer_installation_path / '.build.info')
    }


def get_installation_dir_from_addon_dir(path_like: os.PathLike[str] | str) -> Path | None:
    path = Path(path_like)
    tail = tuple(map(str.casefold, path.parts[-3:]))
    if len(tail) == 3 and tail[1:] == _NORMALISED_ADDON_DIR_PARTS:
        return path.parents[1]


def infer_flavour_from_addon_dir(path: os.PathLike[str] | str) -> Flavour | None:
    maybe_installation_dir = get_installation_dir_from_addon_dir(path)
    if maybe_installation_dir:
        try:
            return _DELECTABLE_DIR_NAMES[maybe_installation_dir.name]['flavour']
        except KeyError:
            return None


def get_installation_version_from_addon_dir(path: os.PathLike[str] | str) -> str | None:
    maybe_installation_dir = get_installation_dir_from_addon_dir(path)
    if maybe_installation_dir:
        product = _DELECTABLE_DIR_NAMES.get(maybe_installation_dir.name)
        if product:
            all_versions = _get_installed_versions(maybe_installation_dir.parent)
            return all_versions[product['code']]
