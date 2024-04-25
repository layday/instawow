from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

import pytest

from instawow.config import ProfileConfig
from instawow.wow_installations import (
    Flavour,
    FlavourVersionRange,
    find_installations,
    get_installation_version_from_addon_dir,
    infer_flavour_from_addon_dir,
)


def test_can_convert_between_flavour_keyed_enum_and_flavour():
    class Foo(Enum):
        Retail = 1
        VanillaClassic = 2
        Classic = 3
        CataclysmClassic = 4

    assert Flavour.from_flavour_keyed_enum(Foo.Retail) is Flavour.Retail
    assert Flavour.Retail.to_flavour_keyed_enum(Foo) is Foo.Retail


@pytest.mark.parametrize('flavour', list(Flavour))
@pytest.mark.parametrize('affine', [True, False])
def test_flavour_groups_vary_by_flavour_and_affinity(
    flavour: Flavour,
    affine: bool,
):
    flavour_groups = flavour.get_flavour_groups(affine)
    if affine:
        if flavour is Flavour.CataclysmClassic:
            assert flavour_groups == [(flavour, Flavour.Classic), None]
        else:
            assert flavour_groups == [(flavour,), None]
    else:
        assert flavour_groups == [(flavour,)]


def test_can_extract_flavour_from_version_number():
    assert FlavourVersionRange.from_version(95000) is FlavourVersionRange.Retail
    assert FlavourVersionRange.from_version(34000) is FlavourVersionRange.Classic
    assert FlavourVersionRange.from_version(12300) is FlavourVersionRange.VanillaClassic


def test_can_extract_flavour_from_version_string():
    assert FlavourVersionRange.from_version('9.50.0') is FlavourVersionRange.Retail
    assert FlavourVersionRange.from_version('3.40.0') is FlavourVersionRange.Classic
    assert FlavourVersionRange.from_version('1.23.0') is FlavourVersionRange.VanillaClassic


def test_can_extract_flavour_from_partial_version_string():
    assert FlavourVersionRange.from_version('9.2') is FlavourVersionRange.Retail
    assert FlavourVersionRange.from_version('3.4') is FlavourVersionRange.Classic
    assert FlavourVersionRange.from_version('3') is FlavourVersionRange.Retail


@pytest.mark.parametrize(
    ('path', 'flavour'),
    [
        (
            'wowzerz/_classic_/Interface/AddOns',
            Flavour.Classic,
        ),
        (
            '/foo/bar/_classic_ptr_/Interface/AddOns',
            Flavour.CataclysmClassic,
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

        def check_output_no_installation(*args, **kwargs):
            return ''

        patcher.setattr('subprocess.check_output', check_output_no_installation)

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

        def check_output_has_installations(*args, **kwargs):
            return '\n'.join(map(str, app_bundle_paths))

        patcher.setattr('subprocess.check_output', check_output_has_installations)

        assert list(find_installations()) == [(p.parent, f) for p, f in app_bundle_paths.items()]


def test_installation_version_extraction_from_addon_dir(
    iw_config: ProfileConfig,
):
    iw_config.addon_dir.parents[2].joinpath('.build.info').write_text("""\
Version!STRING:0|Product!STRING:0
10.9.8.7|wow
""")
    assert get_installation_version_from_addon_dir(iw_config.addon_dir) == '10.9.8.7'
