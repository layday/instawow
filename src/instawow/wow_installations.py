from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path, PurePath
from typing import TypeAlias

from .common import Flavour

_InstallationPath: TypeAlias = Path

_DELECTABLE_DIR_NAMES = {
    '_retail_': Flavour.Retail,
    '_ptr_': Flavour.Retail,
    '_xptr_': Flavour.Retail,
    '_classic_era_': Flavour.VanillaClassic,
    '_classic_era_ptr_': Flavour.VanillaClassic,
    '_classic_': Flavour.Classic,
    '_classic_ptr_': Flavour.Classic,
}

ADDON_DIR_PARTS = ('Interface', 'AddOns')
_NORMALISED_ADDON_DIR_PARTS = tuple(map(str.casefold, ADDON_DIR_PARTS))


def infer_flavour_from_addon_dir(path: os.PathLike[str] | str) -> Flavour | None:
    tail = tuple(map(str.casefold, PurePath(path).parts[-3:]))
    if len(tail) == 3 and tail[1:] == _NORMALISED_ADDON_DIR_PARTS:
        return _DELECTABLE_DIR_NAMES.get(tail[0])


def _find_mac_installations():
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


def find_installations() -> Iterator[tuple[_InstallationPath, Flavour | None]]:
    if sys.platform == 'darwin':
        yield from _find_mac_installations()
