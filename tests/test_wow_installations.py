from __future__ import annotations

import sys
from pathlib import Path

import pytest

from instawow.common import Flavour
from instawow.wow_installations import find_installations, infer_flavour_from_addon_dir


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

        def check_output_no_installation(*args, **kwargs):
            return ''

        patcher.setattr('subprocess.check_output', check_output_no_installation)

        assert set(find_installations()) == set()

    with monkeypatch.context() as patcher:
        app_bundle_paths = {
            Path('/Applications/World of Warcraft/_retail_/World of Warcraft.app'): Flavour.Retail,
            Path(
                '/Applications/World of Warcraft/_classic_/World of Warcraft Classic.app'
            ): Flavour.Classic,
        }

        def check_output_has_installations(*args, **kwargs):
            return '\n'.join(map(str, app_bundle_paths))

        patcher.setattr('subprocess.check_output', check_output_has_installations)

        assert set(find_installations()) == {(p.parent, f) for p, f in app_bundle_paths.items()}
