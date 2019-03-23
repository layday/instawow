
from __future__ import annotations

__all__ = ('Config',)

import os
from pathlib import Path
from typing import Union

import click

from .exceptions import ConfigError


_MaybePath = Union[None, Path, str]


def _normalise_path(path: Union[Path, str]) -> Path:
    return Path(path).expanduser().resolve()


class Config:

    config_dir: Path
    plugin_dir: Path
    addon_dir:  Path

    def __init__(self, *, config_dir: _MaybePath = None,
                 addon_dir: _MaybePath = None) -> None:
        def _config_dir():
            yield os.environ.get('INSTAWOW_CONFIG_DIR')
            yield config_dir
            yield click.get_app_dir('instawow')

        def _addon_dir():
            yield addon_dir
            yield ((self.config_dir / 'addon_dir.txt')
                   .read_text(encoding='utf-8').strip())

        self.config_dir = _normalise_path(next(p for p in _config_dir() if p))
        self.plugin_dir = self.config_dir / 'plugins'

        try:
            self.addon_dir = _normalise_path(next(p for p in _addon_dir() if p))
        except FileNotFoundError:
            raise ConfigError('configuration not written on disk')
        if not self.addon_dir.is_dir():
            raise ConfigError(f"'{self.addon_dir}' is not a directory")

    def write(self) -> Config:
        self.config_dir.mkdir(exist_ok=True)
        self.plugin_dir.mkdir(exist_ok=True)
        (self.config_dir / 'addon_dir.txt').write_text(str(self.addon_dir),
                                                       encoding='utf-8')
        return self
