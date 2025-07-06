from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path
from unittest import mock

import pytest

from instawow.config import ProfileConfig
from instawow.wow_installations import (
    Flavour,
    FlavourVersions,
    Track,
    extract_installation_version_from_addon_dir,
    find_installations,
    get_compatible_flavours,
    infer_flavour_from_addon_dir,
    to_flavourful_enum,
)


def test_can_convert_between_flavour_keyed_enum_and_flavour():
    class Foo(Enum):
        Retail = 1

    assert to_flavourful_enum(Foo.Retail, Flavour) is Flavour.Retail
    assert to_flavourful_enum(Flavour.Retail, Foo) is Foo.Retail


@pytest.mark.parametrize(
    ('track', 'affine', 'expected_flavours'),
    [
        (Track.Retail, False, (Flavour.Retail,)),
        (Track.Retail, True, (Flavour.Retail, None)),
        (Track.VanillaClassic, False, (Flavour.VanillaClassic,)),
        (Track.VanillaClassic, True, (Flavour.VanillaClassic, None)),
        (Track.Classic, False, (Flavour.MistsClassic, Flavour.CataClassic)),
        (Track.Classic, True, (Flavour.MistsClassic, None)),
    ],
)
def test_compatible_flavours_vary_by_track_and_affinity(
    track: Track, affine: bool, expected_flavours: tuple[Flavour | None, ...]
):
    assert get_compatible_flavours(track, affine) == expected_flavours


def test_can_extract_flavour_from_version_number():
    assert FlavourVersions.from_version_number(9_50_00) is FlavourVersions.Retail
    assert FlavourVersions.from_version_number(4_04_00) is FlavourVersions.CataClassic
    assert FlavourVersions.from_version_number(5_05_00) is FlavourVersions.MistsClassic
    assert FlavourVersions.from_version_number(1_23_00) is FlavourVersions.VanillaClassic


def test_can_extract_flavour_from_version_string():
    assert FlavourVersions.from_version_string('9.50.0') is FlavourVersions.Retail
    assert FlavourVersions.from_version_string('4.4.0') is FlavourVersions.CataClassic
    assert FlavourVersions.from_version_string('5.5.0') is FlavourVersions.MistsClassic
    assert FlavourVersions.from_version_string('1.23.0') is FlavourVersions.VanillaClassic


def test_can_extract_flavour_from_partial_version_string():
    assert FlavourVersions.from_version_string('9.2') is FlavourVersions.Retail
    assert FlavourVersions.from_version_string('4.4') is FlavourVersions.CataClassic
    assert FlavourVersions.from_version_string('5.5') is FlavourVersions.MistsClassic
    assert FlavourVersions.from_version_string('3') is FlavourVersions.Retail


@pytest.mark.parametrize(
    ('path', 'flavour'),
    [
        (
            'wowzerz/_classic_/Interface/AddOns',
            Flavour.MistsClassic,
        ),
        (
            '/foo/bar/_classic_ptr_/Interface/AddOns',
            Flavour.MistsClassic,
        ),
        (
            '_classic_era_/Interface/AddOns',
            Flavour.VanillaClassic,
        ),
        (
            '_classic_era_ptr_/Interface/AddOns',
            Flavour.VanillaClassic,
        ),
        (
            'wowzerz/_retail_/Interface/AddOns',
            Flavour.Retail,
        ),
        (
            'anything goes',
            None,
        ),
    ],
)
def test_can_infer_flavour_from_addon_dir(
    path: str,
    flavour: Flavour | None,
):
    assert infer_flavour_from_addon_dir(path) is flavour


@pytest.mark.skipif(sys.platform != 'darwin', reason='Only supported on Mac')
def test_can_find_mac_installations(
    monkeypatch: pytest.MonkeyPatch,
):
    with monkeypatch.context() as patcher:
        patcher.setattr('subprocess.check_output', mock.Mock(return_value=''))
        assert not list(find_installations())

    with monkeypatch.context() as patcher:
        app_bundle_paths = {
            Path('/Applications/World of Warcraft/_retail_/World of Warcraft.app'): {
                'code': 'wow',
                'flavour': Flavour.Retail,
            },
            Path('/Applications/World of Warcraft/_classic_/World of Warcraft Classic.app'): {
                'code': 'wow_classic',
                'flavour': Flavour.MistsClassic,
            },
        }

        patcher.setattr(
            'subprocess.check_output',
            mock.Mock(return_value='\n'.join(map(str, app_bundle_paths))),
        )
        assert list(find_installations()) == [(p.parent, f) for p, f in app_bundle_paths.items()]


def test_installation_version_extraction_from_addon_dir(
    iw_profile_config: ProfileConfig,
):
    iw_profile_config.addon_dir.parents[2].joinpath('.build.info').write_bytes(b"""\
Version!STRING:0|Product!STRING:0
10.9.8.7|wow
""")
    assert extract_installation_version_from_addon_dir(iw_profile_config.addon_dir) == 100908
