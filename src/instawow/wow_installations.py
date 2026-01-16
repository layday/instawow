from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from enum import Enum, StrEnum
from functools import cache, partial
from pathlib import Path
from typing import Literal, Self, TypedDict

from ._utils.iteration import fill


class Flavour(StrEnum):
    Mainline = 'mainline'
    VanillaClassic = 'vanilla_classic'
    TbcClassic = 'tbc_classic'
    WrathClassic = 'wrath_classic'
    TitanClassic = 'titan_classic'
    CataClassic = 'cata_classic'
    MistsClassic = 'mists_classic'
    Classic = MistsClassic

    @classmethod
    def _missing_(cls, value: object):
        return cls.Mainline if value == 'retail' else None  # For back compat.


class FlavourVersions(Enum):
    Mainline = (
        range(1_00_00, 1_13_00),
        range(2_00_00, 2_05_00),
        range(3_00_00, 3_04_00),
        range(4_00_00, 4_04_00),
        range(5_00_00, 5_05_00),
        range(6_00_00, 13_00_00),
    )
    VanillaClassic = (range(1_13_00, 2_00_00),)
    TbcClassic = (range(2_05_00, 3_00_00),)
    WrathClassic = (range(3_04_00, 3_08_00),)
    TitanClassic = (range(3_08_00, 4_00_00),)
    CataClassic = (range(4_04_00, 5_00_00),)
    MistsClassic = (range(5_05_00, 6_00_00),)

    @classmethod
    def from_version_number(cls, version: int) -> Self | None:
        return next((f for f in cls for r in f.value if version in r), None)

    @classmethod
    def from_version_string(cls, version: str) -> Self | None:
        return cls.from_version_number(_parse_version_string(version))


class FlavourTocSuffixes(Enum):
    # https://github.com/Stanzilla/WoWUIBugs/issues/68#issuecomment-830351390
    # https://warcraft.wiki.gg/wiki/TOC_format#Multiple_client_flavors
    Mainline = ('Mainline',)
    VanillaClassic = ('Vanilla', 'Classic')
    TbcClassic = ('TBC', 'BCC', 'Classic')
    WrathClassic = ('Wrath', 'WOTLKC', 'Classic')
    TitanClassic = WrathClassic
    CataClassic = ('Cata', 'Classic')
    MistsClassic = ('Mists', 'Classic')


def to_flavourful_enum[TargetEnumT: Enum](
    source_enum: Enum, target_enum_type: type[TargetEnumT]
) -> TargetEnumT:
    return target_enum_type[source_enum.name]


to_flavour = partial(to_flavourful_enum, target_enum_type=Flavour)
to_flavour_versions = partial(to_flavourful_enum, target_enum_type=FlavourVersions)
to_flavour_toc_suffixes = partial(to_flavourful_enum, target_enum_type=FlavourTocSuffixes)


class _Product(TypedDict):
    code: str
    flavour: Flavour
    subfolder: str


class _NullProduct(TypedDict):
    code: None
    flavour: Flavour
    subfolder: None


type Product = _Product | _NullProduct


def make_null_product(flavour: Flavour) -> _NullProduct:
    return {
        'code': None,
        'flavour': flavour,
        'subfolder': None,
    }


async def _get_current_products(  # pyright: ignore[reportUnusedFunction]  # pragma: no cover
    region: Literal['cn', 'eu', 'kr', 'tw', 'us'],
):
    # See https://wow.tools/ and its spiritual successor https://wago.tools/

    from .http_ctx import web_client

    async with web_client().get(f'https://{region}.version.battle.net/v2/summary') as summary_resp:
        products_bpsv = await summary_resp.text()

    products = _parse_bpsv(products_bpsv)
    wow_product_codes = (
        p['Product'] for p in products if p['Flags'] == '' and p['Product'].startswith('wow')
    )

    for product_code in wow_product_codes:
        async with web_client().get(
            f'https://{region}.version.battle.net/{product_code}/versions'
        ) as versions_resp:
            versions_bpsv = await versions_resp.text()

        versions = _parse_bpsv(versions_bpsv)
        region_version = next((v for v in versions if v['Region'] == region), None)
        if region_version is None:
            continue

        product_config_id = region_version['ProductConfig']

        async with web_client().get(
            f'https://{region}.cdn.blizzard.com/tpr/configs/data/'
            f'{product_config_id[0:2]}/{product_config_id[2:4]}/{product_config_id}'
        ) as product_config_resp:
            product_config = await product_config_resp.json(content_type='binary/octet-stream')

        subfolder = product_config['all']['config']['shared_container_default_subfolder']

        version_string = region_version['VersionsName']
        flavour_version = FlavourVersions.from_version_string(version_string)
        assert flavour_version
        flavour = to_flavour(flavour_version)

        yield _Product(code=product_code, flavour=flavour, subfolder=subfolder)


PRODUCTS: list[_Product] = [
    {'code': 'wow', 'flavour': Flavour.Mainline, 'subfolder': '_retail_'},
    {'code': 'wow_anniversary', 'flavour': Flavour.TbcClassic, 'subfolder': '_anniversary_'},
    {'code': 'wow_beta', 'flavour': Flavour.Mainline, 'subfolder': '_beta_'},
    {'code': 'wow_classic', 'flavour': Flavour.MistsClassic, 'subfolder': '_classic_'},
    {'code': 'wow_classic_beta', 'flavour': Flavour.MistsClassic, 'subfolder': '_classic_beta_'},
    {'code': 'wow_classic_era', 'flavour': Flavour.VanillaClassic, 'subfolder': '_classic_era_'},
    {
        'code': 'wow_classic_era_ptr',
        'flavour': Flavour.TbcClassic,
        'subfolder': '_classic_era_ptr_',
    },
    {'code': 'wow_classic_ptr', 'flavour': Flavour.MistsClassic, 'subfolder': '_classic_ptr_'},
    {'code': 'wowdev', 'flavour': Flavour.Mainline, 'subfolder': '_alpha_'},
    {'code': 'wowdev2', 'flavour': Flavour.VanillaClassic, 'subfolder': '_classic_alpha_'},
    {'code': 'wowe1', 'flavour': Flavour.Mainline, 'subfolder': '_event1_'},
    {'code': 'wowlivetest', 'flavour': Flavour.Mainline, 'subfolder': '_dark_realm_'},
    {'code': 'wowlivetest2', 'flavour': Flavour.Mainline, 'subfolder': '_dark_realm_2_'},
    {'code': 'wowt', 'flavour': Flavour.Mainline, 'subfolder': '_ptr_'},
    {'code': 'wowv', 'flavour': Flavour.MistsClassic, 'subfolder': '_vendor_'},
    {'code': 'wowv10', 'flavour': Flavour.Mainline, 'subfolder': '_vendor10_'},
    {'code': 'wowv2', 'flavour': Flavour.Mainline, 'subfolder': '_vendor2_'},
    {'code': 'wowv3', 'flavour': Flavour.Mainline, 'subfolder': '_vendor3_'},
    {'code': 'wowv4', 'flavour': Flavour.TitanClassic, 'subfolder': '_vendor4_'},
    {'code': 'wowv5', 'flavour': Flavour.TbcClassic, 'subfolder': '_vendor5_'},
    {'code': 'wowv6', 'flavour': Flavour.VanillaClassic, 'subfolder': '_vendor6_'},
    {'code': 'wowv7', 'flavour': Flavour.MistsClassic, 'subfolder': '_vendor7_'},
    {'code': 'wowv8', 'flavour': Flavour.Mainline, 'subfolder': '_vendor8_'},
    {'code': 'wowv9', 'flavour': Flavour.TitanClassic, 'subfolder': '_vendor9_'},
    {'code': 'wowxptr', 'flavour': Flavour.Mainline, 'subfolder': '_xptr_'},
    {'code': 'wowz', 'flavour': Flavour.VanillaClassic, 'subfolder': '_submission_'},
]
_SUBFOLDERS_TO_PRODUCTS = {p['subfolder']: p for p in PRODUCTS}

_ADDON_DIR_PARTS = ('Interface', 'AddOns')
_NORMALISED_ADDON_DIR_PARTS = tuple(map(str.casefold, _ADDON_DIR_PARTS))


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
            yield (installation_path, _SUBFOLDERS_TO_PRODUCTS.get(installation_path.name))


def find_installations() -> Iterator[tuple[Path, _Product | None]]:
    if sys.platform == 'darwin':
        yield from _find_mac_installations()


def _parse_version_string(version_string: str) -> int:
    major, minor, patch = fill(map(int, version_string.split('.')), 0, 3)
    return major * 1_00_00 + minor * 1_00 + patch


def _parse_bpsv(bpsv: str):
    header, *rows = bpsv.splitlines()
    fields = tuple(f[: f.find('!')] for f in header.split('|'))
    return [dict(zip(fields, e.split('|'))) for e in rows if not e.startswith('#')]


@cache
def _extract_installed_versions_from_build_info(outer_installation_path: Path):
    with open(outer_installation_path / '.build.info', encoding='utf-8') as bpsv:
        return {
            e['Product']: _parse_version_string(e['Version']) for e in _parse_bpsv(bpsv.read())
        }


@cache
def _extract_installed_version_from_config_wtf(installation_path: Path):
    with open(installation_path.joinpath('WTF', 'Config.wtf'), 'rb') as config_wtf:
        version_prefix = b'SET lastAddonVersion'
        for line in config_wtf:
            if line.startswith(version_prefix):
                byte_version = line.replace(version_prefix, b'').strip().strip(b'"')
                if byte_version:
                    return int(byte_version)
                break


def extract_installation_dir_from_addon_dir(path_like: os.PathLike[str] | str) -> Path | None:
    path = Path(path_like)
    tail = tuple(map(str.casefold, path.parts[-3:]))
    if len(tail) == 3 and tail[1:] == _NORMALISED_ADDON_DIR_PARTS:
        return path.parents[1]


def extract_installation_version_from_addon_dir(path: os.PathLike[str] | str) -> int | None:
    maybe_installation_dir = extract_installation_dir_from_addon_dir(path)
    if maybe_installation_dir:
        product = _SUBFOLDERS_TO_PRODUCTS.get(maybe_installation_dir.name)
        if product:
            try:
                all_versions = _extract_installed_versions_from_build_info(
                    maybe_installation_dir.parent
                )
            except FileNotFoundError:
                pass
            else:
                version = all_versions.get(product['code'])
                if version:
                    return version

        try:
            return _extract_installed_version_from_config_wtf(maybe_installation_dir)
        except FileNotFoundError:
            return None


def get_addon_dir_from_installation_dir(path_like: os.PathLike[str]) -> Path:
    return Path(path_like, *_ADDON_DIR_PARTS)


def infer_product_from_addon_dir(path: os.PathLike[str] | str) -> _Product | None:
    maybe_installation_dir = extract_installation_dir_from_addon_dir(path)
    if maybe_installation_dir:
        try:
            return _SUBFOLDERS_TO_PRODUCTS[maybe_installation_dir.name]
        except KeyError:
            return None
