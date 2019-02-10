
from __future__ import annotations

from pathlib import Path

import click
import pydantic


__all__ = ('DEFAULT_CONFIG_DIR', 'Config', 'UserConfig')


DEFAULT_CONFIG_DIR = Path(click.get_app_dir('instawow'))


class Config(pydantic.BaseSettings):

    config_dir: Path
    addon_dir: Path

    @pydantic.validator('addon_dir')
    def expand_and_validate_addon_dir(cls, value: Path) -> Path:
        value = value.expanduser().resolve()
        if not value.is_dir():
            raise ValueError(f'{value} is not a directory')
        return value

    def write(self) -> None:
        "Create the profile."
        self.config_dir.mkdir(exist_ok=True)

    class Config:
        env_prefix = 'INSTAWOW_'


class UserConfig(Config):

    config_dir: Path = DEFAULT_CONFIG_DIR

    @classmethod
    def read(cls) -> UserConfig:
        "Attempt to read ``addon_dir`` from disk."
        return cls(addon_dir=(cls(addon_dir='').config_dir/'addon_dir.txt')
                             .read_text(encoding='utf-8'))

    def write(self) -> None:
        "Create the profile and write ``addon_dir`` on disk."
        super().write()
        (self.config_dir/'addon_dir.txt').write_text(str(self.addon_dir),
                                                     encoding='utf-8')
