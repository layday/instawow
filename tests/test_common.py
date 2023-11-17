from __future__ import annotations

from enum import Enum

from instawow.common import Flavour, FlavourVersionRange


def test_can_convert_between_flavour_keyed_enum_and_flavour():
    class Foo(Enum):
        Retail = 1
        VanillaClassic = 2
        Classic = 3

    assert Flavour.from_flavour_keyed_enum(Foo.Retail) is Flavour.Retail
    assert Flavour.Retail.to_flavour_keyed_enum(Foo) is Foo.Retail


def test_can_extract_flavour_from_version_number():
    assert FlavourVersionRange.from_version_number(95000) is FlavourVersionRange.Retail
    assert FlavourVersionRange.from_version_number(34000) is FlavourVersionRange.Classic
    assert FlavourVersionRange.from_version_number(12300) is FlavourVersionRange.VanillaClassic


def test_can_extract_flavour_from_version_string():
    assert FlavourVersionRange.from_version_string('9.50.0') is FlavourVersionRange.Retail
    assert FlavourVersionRange.from_version_string('3.40.0') is FlavourVersionRange.Classic
    assert FlavourVersionRange.from_version_string('1.23.0') is FlavourVersionRange.VanillaClassic


def test_can_extract_flavour_from_partial_version_string():
    assert FlavourVersionRange.from_version_string('9.2') is FlavourVersionRange.Retail
    assert FlavourVersionRange.from_version_string('3.4') is FlavourVersionRange.Classic
    assert FlavourVersionRange.from_version_string('3') is FlavourVersionRange.Retail
