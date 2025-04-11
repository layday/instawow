from __future__ import annotations

import os
import sys
from functools import partial
from pathlib import Path

from .. import NAME

_get_home_dir = partial(os.environ.get, f'{NAME.upper()}_HOME')


def get_config_dir(*parts: str):
    home = _get_home_dir()
    if home:
        return Path(home, 'config', *parts)

    parent_dir = os.environ.get('XDG_CONFIG_HOME')

    if not parent_dir:
        if sys.platform == 'darwin':
            parent_dir = Path.home() / 'Library' / 'Application Support'
        elif sys.platform == 'win32':
            parent_dir = os.environ.get('APPDATA')

    if not parent_dir:
        parent_dir = Path.home() / '.config'

    return Path(parent_dir, NAME, *parts)


def get_cache_dir(*parts: str):
    home = _get_home_dir()
    if home:
        return Path(home, 'cache', *parts)

    parent_dir = os.environ.get('XDG_CACHE_HOME')

    if not parent_dir:
        if sys.platform == 'darwin':
            parent_dir = Path.home() / 'Library' / 'Caches'
        elif sys.platform == 'win32':
            parent_dir = os.environ.get('LOCALAPPDATA')

    if not parent_dir:
        parent_dir = Path.home() / '.cache'

    return Path(parent_dir, NAME, *parts)


def get_state_dir(*parts: str):
    home = _get_home_dir()
    if home:
        return Path(home, 'state', *parts)

    parent_dir = os.environ.get('XDG_STATE_HOME')

    if not parent_dir and sys.platform not in {'darwin', 'win32'}:
        parent_dir = Path.home() / '.local' / 'state'

    if not parent_dir:
        return get_config_dir()

    return Path(parent_dir, NAME, *parts)
