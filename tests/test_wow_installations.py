from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path
from unittest import mock

import pytest

from instawow.config import ProfileConfig
from instawow.wow_installations import (
    Flavour,
    extract_installation_version_from_addon_dir,
    find_installations,
    infer_flavour_from_addon_dir,
    to_flavourful_enum,
)


def test_class_iter_only_returns_supported_flavours():
    assert list(Flavour) == [Flavour.Retail, Flavour.VanillaClassic, Flavour.Classic]


def test_can_convert_between_flavour_keyed_enum_and_flavour():
    class Foo(Enum):
        Retail = 1
        VanillaClassic = 2
        Classic = 3
        MistsClassic = 4

    assert to_flavourful_enum(Foo.Retail, Flavour) is Flavour.Retail
    assert to_flavourful_enum(Flavour.Retail, Foo) is Foo.Retail


@pytest.mark.parametrize('flavour', Flavour)
@pytest.mark.parametrize('affine', [True, False])
def test_flavour_groups_vary_by_flavour_and_affinity(
    flavour: Flavour,
    affine: bool,
):
    flavour_groups = flavour.get_flavour_groups(affine)
    if affine:
        assert flavour_groups == (
            # [(flavour, Flavour.CataClassic), None]
            # if flavour is Flavour.Classic
            # else
            [(flavour,), None]
        )
    else:
        assert flavour_groups == [(flavour,)]


def test_can_extract_flavour_from_version_number():
    assert Flavour.from_version_number(9_50_00) is Flavour.Retail
    assert Flavour.from_version_number(4_04_00) is Flavour.Classic
    assert Flavour.from_version_number(5_05_00) is Flavour.MistsClassic
    assert Flavour.from_version_number(1_23_00) is Flavour.VanillaClassic


def test_can_extract_flavour_from_version_string():
    assert Flavour.from_version_string('9.50.0') is Flavour.Retail
    assert Flavour.from_version_string('4.4.0') is Flavour.Classic
    assert Flavour.from_version_string('5.5.0') is Flavour.MistsClassic
    assert Flavour.from_version_string('1.23.0') is Flavour.VanillaClassic


def test_can_extract_flavour_from_partial_version_string():
    assert Flavour.from_version_string('9.2') is Flavour.Retail
    assert Flavour.from_version_string('4.4') is Flavour.Classic
    assert Flavour.from_version_string('5.5') is Flavour.MistsClassic
    assert Flavour.from_version_string('3') is Flavour.Retail


@pytest.mark.parametrize(
    ('path', 'flavour'),
    [
        (
            'wowzerz/_classic_/Interface/AddOns',
            Flavour.Classic,
        ),
        (
            '/foo/bar/_classic_ptr_/Interface/AddOns',
            Flavour.Classic,
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
                'flavour': Flavour.Classic,
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
