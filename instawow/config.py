
from __future__ import annotations

__all__ = ('Config',)

from pathlib import Path
from typing import Optional

import click
import pydantic



_my_path = Path(__file__)
_default_config_dir = lambda: Path(click.get_app_dir('instawow'))


class _Config(pydantic.BaseSettings):

    ValidationError = pydantic.ValidationError

    config_dir: Path = _my_path
    addon_dir: Path

    @pydantic.validator('config_dir', always=True, pre=True)
    def __ensure_config_dir(cls, value: Path) -> Path:
        if value == _my_path:
            value = _default_config_dir()
        return value

    @pydantic.validator('addon_dir')
    def __transform_addon_dir(cls, value: Path) -> Path:
        value = Path(value).expanduser().resolve()
        if not value.is_dir():
            raise ValueError('folder does not exist')
        return value

    @property
    def logger_dir(self) -> Path:
        return self.config_dir / 'logs'

    @property
    def plugin_dir(self) -> Path:
        return self.config_dir / 'plugins'

    def json(self, **kwargs) -> str:
        return super().json(exclude={'config_dir'}, indent=2)

    @classmethod
    def read(cls, config_dir: Optional[Path] = None) -> _Config:
        config_dir = config_dir or _default_config_dir()
        return cls.parse_raw((config_dir / 'config.json')
                             .read_text(encoding='utf-8'))

    def write(self) -> _Config:
        for dir_ in (self.config_dir,
                     self.plugin_dir):
            dir_.mkdir(exist_ok=True)

        (self.config_dir / 'config.json').write_text(self.json(),
                                                     encoding='utf-8')
        return self

    class Config:
        env_prefix = 'INSTAWOW_'


Config = _Config
