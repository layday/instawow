from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir
from typing import Any

import click
import pydantic

try:
    from typing import Literal      # type: ignore
except ImportError:
    from typing_extensions import Literal


_TEMP_DIR = Path(gettempdir())

_default_config_dir = lambda: click.get_app_dir('instawow')


class _Config(pydantic.BaseSettings):

    config_dir: Path
    addon_dir: Path
    temp_dir: Path = _TEMP_DIR / 'instawow'
    game_flavour: Literal['retail', 'classic']

    @pydantic.validator('config_dir', 'addon_dir')
    def __expand_paths(cls, value: Path) -> Path:
        return Path(value).expanduser().resolve()

    @classmethod
    def read(cls) -> _Config:
        dummy_config = cls(addon_dir='', game_flavour='retail')
        return cls.parse_raw(dummy_config.config_file.read_text(encoding='utf-8'))

    def __init__(__pydantic_self__, **values: Any) -> None:
        values = __pydantic_self__._build_values(values)
        if not values.get('config_dir'):
            values = {**values, 'config_dir': _default_config_dir()}
        super(pydantic.BaseSettings, __pydantic_self__).__init__(**values)

    def json(self, **kwargs: Any) -> str:
        kwargs = {'exclude': {'config_dir'}, 'indent': 2, **kwargs}
        return super().json(**kwargs)

    def write(self) -> _Config:
        for dir_ in (self.config_dir,
                     self.logger_dir,
                     self.plugin_dir,
                     self.temp_dir,):
            dir_.mkdir(exist_ok=True)

        self.config_file.write_text(self.json(), encoding='utf-8')
        return self

    @property
    def is_classic(self) -> bool:
        return self.game_flavour == 'classic'

    @property
    def config_file(self) -> Path:
        return self.config_dir / 'config.json'

    @property
    def logger_dir(self) -> Path:
        return self.config_dir / 'logs'

    @property
    def plugin_dir(self) -> Path:
        return self.config_dir / 'plugins'

    class Config:
        case_insensitive = True
        env_prefix = 'INSTAWOW_'


Config = _Config
