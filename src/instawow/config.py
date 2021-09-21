from __future__ import annotations

from enum import Enum
import os
from pathlib import Path, PurePath
from tempfile import gettempdir

import click
from loguru import logger
from pydantic import BaseSettings, Field, PydanticValueError, validator
from pydantic.env_settings import SettingsSourceCallable

from .utils import trash


class _PathNotWritableDirectoryError(PydanticValueError):
    code = 'path.not_writable_directory'
    msg_template = '"{path}" is not a writable directory'


_novalidate = '__novalidate__'


def _get_default_config_dir() -> Path:
    return Path(click.get_app_dir('instawow'))


def _get_default_temp_dir() -> Path:
    return Path(gettempdir(), 'instawow')


def _expand_path(value: Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(value)))


def _is_writable_dir(value: Path) -> bool:
    return value.is_dir() and os.access(value, os.W_OK)


def _customise_sources(
    init_settings: SettingsSourceCallable,
    env_settings: SettingsSourceCallable,
    file_secret_settings: SettingsSourceCallable,
) -> tuple[SettingsSourceCallable, ...]:
    # Prioritise env vars
    return (env_settings, init_settings)


class BaseConfig(
    BaseSettings,
    env_prefix='INSTAWOW_',
    customise_sources=_customise_sources,
):
    pass


class Flavour(str, Enum):
    # The latest classic version is always aliased to "classic".
    # The logic here is that should WoW Classic not be discontinued
    # it will continue to be updated in place so that new Classic versions
    # will inherit the "_classic_" folder.  This way we won't have to
    # perform a migration or require user intervention.
    retail = 'retail'
    vanilla_classic = 'vanilla_classic'
    burning_crusade_classic = 'classic'


class Config(BaseConfig):
    config_dir: Path = Field(default_factory=_get_default_config_dir)
    profile: str = Field(min_length=1, strip_whitespace=True)
    addon_dir: Path
    game_flavour: Flavour
    temp_dir: Path = Field(default_factory=_get_default_temp_dir)
    auto_update_check: bool = True

    @validator('config_dir', 'addon_dir', 'temp_dir')
    def _expand_path(cls, value: Path) -> Path:
        return _expand_path(value)

    @validator('addon_dir')
    def _validate_path_is_writable_dir(cls, value: Path) -> Path:
        if value.name == _novalidate:
            return value
        elif not _is_writable_dir(value):
            raise _PathNotWritableDirectoryError(path=value)
        else:
            return value

    @staticmethod
    def infer_flavour(folder: os.PathLike[str] | str) -> Flavour:
        tail = tuple(map(str.casefold, PurePath(folder).parts[-3:]))
        if len(tail) != 3 or tail[1:] != ('interface', 'addons'):
            return Flavour.retail
        elif tail[0] in {'_classic_era_', '_classic_era_ptr_'}:
            return Flavour.vanilla_classic
        elif tail[0] in {'_classic_', '_classic_beta_', '_classic_ptr_'}:
            return Flavour.burning_crusade_classic
        else:
            return Flavour.retail

    @classmethod
    def get_dummy_config(cls, **kwargs: object) -> Config:
        "Create a dummy configuration with default values."
        defaults = {
            'profile': _novalidate,
            'addon_dir': _novalidate,
            'game_flavour': Flavour.retail,
        }
        dummy_config = cls.parse_obj({**defaults, **kwargs})
        return dummy_config

    @classmethod
    def list_profiles(cls) -> list[str]:
        "List the profiles contained in ``config_dir``."
        dummy_config = cls.get_dummy_config()
        profiles = [c.parent.name for c in dummy_config.config_dir.glob('profiles/*/config.json')]
        return profiles

    @classmethod
    def read(cls, profile: str) -> Config:
        "Read the configuration from disk."
        dummy_config = cls.get_dummy_config(profile=profile)
        config = cls.parse_file(dummy_config.config_file, encoding='utf-8')
        return config

    def ensure_dirs(self) -> Config:
        "Create the various folders used by instawow."
        for dir_ in [
            self.config_dir,
            self.profile_dir,
            self.logging_dir,
            self.plugin_dir,
            self.temp_dir,
            self.cache_dir,
        ]:
            dir_.mkdir(exist_ok=True, parents=True)
        return self

    def write(self) -> Config:
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

    def delete(self) -> None:
        "Delete the configuration files associated with this profile."
        trash((self.profile_dir,), dest=self.temp_dir, missing_ok=True)

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


def setup_logging(
    config: Config, log_level: str = 'INFO', log_to_stderr: bool = False
) -> int | None:
    import logging

    class InterceptHandler(logging.Handler):  # pragma: no cover
        logging_filename = getattr(logging, '__file__', None)

        def emit(self, record: logging.LogRecord) -> None:
            # Get the corresponding Loguru level if it exists
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # Find caller from where the logged message originated
            frame = logging.currentframe()
            depth = 2
            while frame and frame.f_code.co_filename == self.logging_filename:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=log_level)

    if not log_to_stderr:
        (handler_id,) = logger.configure(
            handlers=[
                {
                    'sink': config.logging_dir / 'error.log',
                    'level': log_level,
                    'rotation': '5 MB',
                    'retention': 5,  # Number of log files to keep
                    'enqueue': True,
                },
            ]
        )
        return handler_id
