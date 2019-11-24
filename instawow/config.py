from __future__ import annotations

from pathlib import Path
from tempfile import gettempdir
from typing import Any, Dict

import click
import pydantic

try:
    from typing import Literal
except ImportError:
    from typing_extensions import Literal


_TEMP_DIR = Path(gettempdir()) / 'instawow'

_default_config_dir = lambda: click.get_app_dir('instawow')


class _Config(pydantic.BaseSettings):

    config_dir: Path
    addon_dir: Path
    temp_dir: Path = _TEMP_DIR
    game_flavour: Literal['retail', 'classic']

    @pydantic.validator('config_dir', 'addon_dir')
    def __expand_paths(cls, value: Path) -> Path:
        return Path(value).expanduser().resolve()

    def _build_values(self, init_kwargs: Dict[str, Any]) -> Dict[str, Any]:
        values = {**init_kwargs, **self._build_environ()}     # Prioritise env vars
        if not values.get('config_dir'):
            values['config_dir'] = _default_config_dir()
        return values

    @classmethod
    def read(cls) -> _Config:
        dummy_config = cls(addon_dir='', game_flavour='retail')
        return cls.parse_raw(dummy_config.config_file.read_text(encoding='utf-8'))

    def json(self, **kwargs: Any) -> str:
        kwargs = {'exclude': {'config_dir'}, 'indent': 2, **kwargs}
        return super().json(**kwargs)

    def ensure_dirs(self) -> _Config:
        self.config_dir.mkdir(exist_ok=True, parents=True)
        for dir_ in self.logger_dir, self.plugin_dir, self.temp_dir:
            dir_.mkdir(exist_ok=True)
        return self

    def write(self) -> _Config:
        self.ensure_dirs()
        self.config_file.write_text(self.json(), encoding='utf-8')
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

    class Config:
        env_prefix = 'INSTAWOW_'


Config = _Config
