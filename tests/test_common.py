from __future__ import annotations

from enum import Enum

from instawow.common import Flavour, FlavourVersionRange, infer_flavour_from_path


def test_can_convert_between_flavour_keyed_enum_and_flavour():
    class Foo(Enum):
        retail = 1

    assert Flavour.from_flavour_keyed_enum(Foo.retail) is Flavour.retail
    assert Flavour.retail.to_flavour_keyed_enum(Foo) is Foo.retail


def test_can_extract_flavour_from_version_number():
    assert FlavourVersionRange.from_version_number(95000) is FlavourVersionRange.retail
    assert FlavourVersionRange.from_version_number(34000) is FlavourVersionRange.classic
    assert FlavourVersionRange.from_version_number(12300) is FlavourVersionRange.vanilla_classic


def test_can_extract_flavour_from_version_string():
    assert FlavourVersionRange.from_version_string('9.50.0') is FlavourVersionRange.retail
    assert FlavourVersionRange.from_version_string('3.40.0') is FlavourVersionRange.classic
    assert FlavourVersionRange.from_version_string('1.23.0') is FlavourVersionRange.vanilla_classic


def test_can_extract_flavour_from_partial_version_string():
    assert FlavourVersionRange.from_version_string('9.2') is FlavourVersionRange.retail
    assert FlavourVersionRange.from_version_string('3.4') is FlavourVersionRange.classic
    assert FlavourVersionRange.from_version_string('3') is FlavourVersionRange.retail


def test_can_infer_flavour_from_path():
    # fmt: off
    assert infer_flavour_from_path('wowzerz/_classic_/Interface/AddOns') is Flavour.classic
    assert infer_flavour_from_path('/foo/bar/_classic_beta_/Interface/AddOns') is Flavour.classic
    assert infer_flavour_from_path('/foo/bar/_classic_ptr_/Interface/AddOns') is Flavour.classic
    assert infer_flavour_from_path('_classic_era_/Interface/AddOns') is Flavour.vanilla_classic
    assert infer_flavour_from_path('_classic_era_beta_/Interface/AddOns') is Flavour.vanilla_classic
    assert infer_flavour_from_path('_classic_era_ptr_/Interface/AddOns') is Flavour.vanilla_classic
    assert infer_flavour_from_path('wowzerz/_retail_/Interface/AddOns') is Flavour.retail
    assert infer_flavour_from_path('anything goes') is Flavour.retail
    # fmt: on
