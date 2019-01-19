
from os import environ
from pathlib import Path
import typing as T

import click
import pydantic


_DEFAULT_CONFIG_DIR = Path(click.get_app_dir('instawow'))


class Config(pydantic.BaseSettings):

    addon_dir: Path
    config_dir: Path = _DEFAULT_CONFIG_DIR

    @pydantic.validator('addon_dir')
    def _prepare_addon_dir(cls, value: Path) -> Path:
        value = value.expanduser().resolve()
        if not value.is_dir():
            raise ValueError
        return value

    @pydantic.validator('config_dir')
    def _prepare_config_dir(cls, value: Path) -> Path:
        value.mkdir(exist_ok=True)
        return value


class UserConfig(Config):

    @classmethod
    def read(cls):  # -> UserConfig
        "Attempt to read the config from the default path."
        return cls(addon_dir=(_DEFAULT_CONFIG_DIR/'addon_dir.txt')
                             .read_text(encoding='utf-8'))

    def write(self) -> None:
        "Write ``self.addon_dir`` on disk."
        (self.config_dir/'addon_dir.txt').write_text(str(self.addon_dir),
                                                     encoding='utf-8')
