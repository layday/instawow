from __future__ import annotations

import enum
import os
import sys
from collections.abc import Iterator
from enum import Enum, StrEnum
from functools import cache
from pathlib import Path
from typing import Self, TypedDict

from ._utils.iteration import fill


class Flavour(StrEnum):
    # The current Classic version is always aliased to "classic".
    # The assumption here is that should Classic not be discontinued
    # it will continue to be updated in place so that new Classic versions
    # will inherit the "_classic_" folder.  This means we won't have to
    # migrate Classic profiles either automatically or by requiring user
    # intervention for new Classic releases.
    Retail = 'retail'
    VanillaClassic = 'vanilla_classic'
    WrathClassic = 'wrath_classic'
    MistsClassic = 'mists_classic'
    Classic = 'classic'
    CataClassic = Classic

    _UNSUPPORTED = enum.nonmember(
        (
            WrathClassic,
            MistsClassic,
        )
    )

    @classmethod
    def iter_supported(cls) -> Iterator[Self]:
        return (m for m in cls if m not in cls._UNSUPPORTED)

    @classmethod
    def from_flavourful_enum(cls, flavour_keyed_enum: Enum) -> Self:
        return cls[flavour_keyed_enum.name]

    def to_flavourful_enum[EnumT: Enum](self, flavour_keyed_enum: type[EnumT]) -> EnumT:
        return flavour_keyed_enum[self.name]

    def get_flavour_groups(self, affine: bool) -> list[tuple[Flavour, ...] | None]:
        match (self, affine):
            # case (self.__class__.Classic, True):
            #     return [(self, self.__class__.CataClassic), None]
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
        range(6_00_00, 12_00_00),
    )
    VanillaClassic = (range(1_13_00, 2_00_00),)
    WrathClassic = (range(3_04_00, 4_00_00),)
    CataClassic = (range(4_04_00, 5_00_00),)
    MistsClassic = (range(5_05_00, 6_00_00),)
    Classic = CataClassic

    @classmethod
    def from_version(cls, version: int | str) -> Self | None:
        version_number = version if isinstance(version, int) else _parse_version_string(version)
        return next((f for f in cls if f.contains(version_number)), None)

    def contains(self, version: int | str) -> bool:
        version_number = version if isinstance(version, int) else _parse_version_string(version)
        return any(version_number in r for r in self.value)


class FlavourTocSuffixes(Enum):
    # https://github.com/Stanzilla/WoWUIBugs/issues/68#issuecomment-830351390
    # https://warcraft.wiki.gg/wiki/TOC_format#Multiple_client_flavors
    Retail = ('Mainline',)
    VanillaClassic = ('Vanilla', 'Classic')
    WrathClassic = ('Wrath', 'WOTLKC', 'Classic')
    CataClassic = ('Cata', 'Classic')
    MistsClassic = ('Mists', 'Classic')
    Classic = CataClassic


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
        'flavour': Flavour.MistsClassic,
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


def _parse_version_string(version_string: str) -> int:
    major, minor, patch = fill(map(int, version_string.split('.')), 0, 3)
    return major * 1_00_00 + minor * 1_00 + patch


def _read_info(info_path: Path):
    with open(info_path, encoding='utf-8') as info:
        header = next(info)
        fields = tuple(f[: f.find('!')] for f in header.rstrip().split('|'))
        return [dict(zip(fields, e.rstrip().split('|'))) for e in info if not e.startswith('#')]


@cache
def _get_installed_versions_from_build_info(outer_installation_path: Path):
    return {
        e['Product']: _parse_version_string(e['Version'])
        for e in _read_info(outer_installation_path / '.build.info')
    }


@cache
def _get_installed_version_from_config_wtf(installation_path: Path):
    with open(installation_path.joinpath('WTF', 'Config.wtf'), 'rb') as config_wtf:
        version_prefix = b'SET lastAddonVersion'
        for line in config_wtf:
            if line.startswith(version_prefix):
                byte_version = line.replace(version_prefix, b'').strip().strip(b'"')
                if byte_version:
                    return int(byte_version)
                break


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


def get_installation_version_from_addon_dir(path: os.PathLike[str] | str) -> int | None:
    maybe_installation_dir = get_installation_dir_from_addon_dir(path)
    if maybe_installation_dir:
        product = _DELECTABLE_DIR_NAMES.get(maybe_installation_dir.name)
        if product:
            try:
                all_versions = _get_installed_versions_from_build_info(
                    maybe_installation_dir.parent
                )
            except FileNotFoundError:
                pass
            else:
                version = all_versions.get(product['code'])
                if version:
                    return version

        try:
            return _get_installed_version_from_config_wtf(maybe_installation_dir)
        except FileNotFoundError:
            return None
