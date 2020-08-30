from __future__ import annotations

import json
import os
from pathlib import Path
from shutil import copytree, ignore_patterns
from tempfile import gettempdir
from typing import Any, Dict, List, Union

import click
from loguru import logger
from pydantic import BaseSettings, Extra, Field, PydanticValueError, validator

from .utils import Literal, trash

__novalidate__ = '__novalidate__'


class _PathNotWritableDirectoryError(PydanticValueError):
    code = 'path.not_writable_directory'
    msg_template = '"{path}" is not a writable directory'


def _get_default_config_dir() -> Path:
    return Path(click.get_app_dir('instawow'))


def _validate_expand_path(value: Path) -> Path:
    try:
        return value.expanduser().resolve()
    except RuntimeError as error:
        # pathlib will raise a ``RuntimeError`` for non-existent ~users
        raise ValueError(str(error)) from error


def _validate_path_is_writable_dir(value: Path) -> Path:
    if not (value.is_dir() and os.access(value, os.W_OK)):
        raise _PathNotWritableDirectoryError(path=value)

    return value


class BaseConfig(BaseSettings):
    def _build_values(
        self,
        init_kwargs: Dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        # Prioritise env vars
        return {**init_kwargs, **self._build_environ()}


class _GlobalConfig(BaseConfig):
    config_dir: Path = Field(default_factory=_get_default_config_dir)
    profile: str = Field('__default__', min_length=1, strip_whitespace=True)
    addon_dir: Path
    game_flavour: Literal['retail', 'classic']
    auto_update_check: bool = True
    temp_dir: Path = Path(gettempdir()) / 'instawow'

    class Config:  # type: ignore
        env_prefix = 'INSTAWOW_'
        extra = Extra.allow
        validate_assignment = True

    @validator('config_dir', 'addon_dir', 'temp_dir')
    def _validate_expand_path(cls, value: Path) -> Path:
        return _validate_expand_path(value)

    @validator('addon_dir')
    def _validate_path_is_writable_dir(cls, value: Path) -> Path:
        if value.name == __novalidate__:
            return value
        return _validate_path_is_writable_dir(value)

    @classmethod
    def get_dummy_config(cls, **kwargs: Any) -> _GlobalConfig:
        "Create a dummy configuration with default values."
        template = {'game_flavour': 'retail', 'addon_dir': __novalidate__}
        dummy_config = cls.parse_obj({**template, **kwargs})
        return dummy_config

    @classmethod
    def list_profiles(cls) -> List[str]:
        "List the profiles contained in the default ``config_dir``."
        dummy_config = cls.get_dummy_config()
        profiles = [f.name for f in (dummy_config.config_dir / 'profiles').iterdir() if f.is_dir()]
        return profiles

    @classmethod
    def read(cls, profile: str) -> _GlobalConfig:
        "Read the configuration from disk."
        dummy_config = cls.get_dummy_config(profile=profile)
        dummy_config.migrate_legacy_dirs()
        config = cls.parse_raw(dummy_config.config_file.read_text(encoding='utf-8'))
        if dummy_config.profile != config.profile:
            raise ValueError(
                'profile location does not match profile value of '
                f'"{config.profile}" in {dummy_config.config_file}'
            )
        return config

    def ensure_dirs(self) -> _GlobalConfig:
        "Create the various folders used by instawow."
        for dir_ in (
            self.config_dir,
            self.profile_dir,
            self.logging_dir,
            self.plugin_dir,
            self.temp_dir,
            self.cache_dir,
        ):
            dir_.mkdir(exist_ok=True, parents=True)
        return self

    def write(self) -> _GlobalConfig:
        """Write the configuration on disk.

        ``write``, unlike ``ensure_dirs``, should only be called when configuring
        instawow.  This means that environment overrides should only be persisted
        if made during configuration.
        """
        self.ensure_dirs()
        includes = {'addon_dir', 'game_flavour', 'profile'}
        output = self.json(include=includes, indent=2)
        self.config_file.write_text(output, encoding='utf-8')
        return self

    def migrate_legacy_dirs(self) -> _GlobalConfig:
        "Migrate a profile-less configuration to the new format."
        legacy_config_file = self.config_dir / 'config.json'
        if (
            self.profile == self.__field_defaults__['profile']
            and not self.profile_dir.exists()
            and legacy_config_file.exists()
        ):
            legacy_json = json.loads(legacy_config_file.read_text(encoding='utf-8'))
            legacy_json.pop('profile', None)
            legacy_config = self.parse_obj(legacy_json)
            ignores = ignore_patterns('profiles')

            logger.info('migrating legacy configuration')
            copytree(self.config_dir, self.profile_dir, ignore=ignores)
            legacy_config.write()
            trash(
                [i for i in self.config_dir.iterdir() if i.name != 'profiles'], dst=self.temp_dir
            )

        return self

    def delete(self) -> None:
        "Delete the configuration files associated with this profile."
        trash((self.ensure_dirs().profile_dir,), dst=self.temp_dir, missing_ok=True)

    @property
    def is_classic(self) -> bool:
        return self.game_flavour == 'classic'

    @property
    def is_retail(self) -> bool:
        return self.game_flavour == 'retail'

    @property
    def profile_dir(self) -> Path:
        return self.config_dir / 'profiles' / self.profile

    @property
    def logging_dir(self) -> Path:
        return self.profile_dir / 'logs'

    @property
    def plugin_dir(self) -> Path:
        return self.profile_dir / 'plugins'

    @property
    def config_file(self) -> Path:
        return self.profile_dir / 'config.json'

    @property
    def db_file(self) -> Path:
        return self.profile_dir / 'db.sqlite'

    @property
    def cache_dir(self) -> Path:
        return self.temp_dir / 'cache'


Config = _GlobalConfig


def setup_logging(config: _GlobalConfig, log_level: Union[int, str] = 'INFO') -> int:
    import logging

    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord):
            # Get the corresponding Loguru level if it exists
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # Find caller from where the logged message originated
            frame = logging.currentframe()
            depth = 2
            while frame and frame.f_code.co_filename == getattr(logging, '__file__', None):
                frame = frame.f_back
                depth += 1

            logger.opt(
                depth=depth,
                exception=record.exc_info,  # type: ignore
            ).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=log_level)
    handler = {
        'sink': config.logging_dir / 'error.log',
        'level': log_level,
        'rotation': '1 MB',
        'enqueue': True,
    }
    (handler_id,) = logger.configure(handlers=(handler,))
    return handler_id
