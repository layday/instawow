
from __future__ import annotations

import os
from pathlib import Path
from typing import Union

import click


__all__ = ('Config',)


MaybePath = Union[None, Path, str]


class Config:

    config_dir: Path
    plugin_dir: Path
    addon_dir:  Path

    def __init__(self, *, config_dir: MaybePath = None,
                 addon_dir: MaybePath = None) -> None:
        self.config_dir = Path(os.environ.get('INSTAWOW_CONFIG_DIR') or
                               config_dir or
                               click.get_app_dir('instawow'))
        self.plugin_dir = self.config_dir / 'plugins'

        if not addon_dir:
            addon_dir = ((self.config_dir / 'addon_dir.txt')
                         .read_text(encoding='utf-8').strip())

        addon_dir = Path(addon_dir).expanduser().resolve()
        if not addon_dir.is_dir():
            raise ValueError(f'{addon_dir} is not a directory')
        self.addon_dir = addon_dir

    def write(self) -> None:
        self.config_dir.mkdir(exist_ok=True)
        (self.config_dir / 'addon_dir.txt').write_text(str(self.addon_dir),
                                                       encoding='utf-8')
        self.plugin_dir.mkdir(exist_ok=True)
