from __future__ import annotations

import os
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict

import click
from pydantic import BaseSettings, Extra, Field, validator

from .utils import Literal


def _get_default_config_dir() -> Path:
    return Path(click.get_app_dir('instawow'))


class BaseConfig(BaseSettings):
    def _build_values(self, init_kwargs: Dict[str, Any], _env_file: Any = None) -> Dict[str, Any]:
        # Prioritise env vars
        return {**init_kwargs, **self._build_environ(_env_file)}


class _Config(BaseConfig):
    config_dir: Path = Field(default_factory=_get_default_config_dir)
    addon_dir: Path
    temp_dir: Path = Path(gettempdir()) / 'instawow'
    game_flavour: Literal['retail', 'classic']
    auto_update_check: bool = True

    class Config:
        env_prefix = 'INSTAWOW_'
        extra = Extra.allow

    @validator('config_dir', 'addon_dir', 'temp_dir')
    def _expand_paths(cls, value: Path) -> Path:
        try:
            return value.expanduser().resolve()
        except RuntimeError as error:
            # pathlib will raise RuntimeError for non-existent ~users
            raise ValueError(str(error)) from error

    @validator('addon_dir')
    def _check_writable(cls, value: Path) -> Path:
        if not (value.is_dir() and os.access(value, os.W_OK)):
            raise ValueError('must be a writable directory')
        return value

    @classmethod
    def read(cls) -> _Config:
        dummy_config = cls(addon_dir='', game_flavour='retail')
        return cls.parse_raw(dummy_config.config_file.read_text(encoding='utf-8'))

    def ensure_dirs(self) -> _Config:
        self.config_dir.mkdir(exist_ok=True, parents=True)
        for dir_ in self.logger_dir, self.plugin_dir, self.temp_dir, self.cache_dir:
            dir_.mkdir(exist_ok=True)
        return self

    def write(self) -> _Config:
        # This is separate from ``ensure_dirs`` because configuration
        # values are considered to be transient if overridden by an
        # env var, e.g. to bypass the cache
        self.ensure_dirs()
        output = self.json(include={'addon_dir', 'game_flavour'}, indent=2)
        self.config_file.write_text(output, encoding='utf-8')
        return self

    @property
    def is_classic(self) -> bool:
        return self.game_flavour == 'classic'

    @property
    def is_retail(self) -> bool:
        return self.game_flavour == 'retail'

    @property
    def config_file(self) -> Path:
        return self.config_dir / 'config.json'

    @property
    def logger_dir(self) -> Path:
        return self.config_dir / 'logs'

    @property
    def plugin_dir(self) -> Path:
        return self.config_dir / 'plugins'

    @property
    def cache_dir(self) -> Path:
        return self.temp_dir / 'cache'


Config = _Config
