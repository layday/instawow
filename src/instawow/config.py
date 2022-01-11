from __future__ import annotations

from collections.abc import Iterable, Set
import json
import os
from pathlib import Path, PurePath
import sys
from tempfile import gettempdir
import typing
from typing import Any

import click
from loguru import logger
from pydantic import BaseModel, BaseSettings, Field, PydanticValueError, SecretStr, validator
from pydantic.env_settings import SettingsSourceCallable

from .common import Flavour
from .utils import trash


class _PathNotWritableDirectoryError(PydanticValueError):
    code = 'path.not_writable_directory'
    msg_template = '"{path}" is not a writable directory'


def _expand_path(value: Path):
    return Path(os.path.abspath(os.path.expanduser(value)))


def _is_writable_dir(value: Path):
    return value.is_dir() and os.access(value, os.W_OK)


def _ensure_dirs(dirs: Iterable[Path]):
    for dir_ in dirs:
        dir_.mkdir(exist_ok=True, parents=True)


def _write_config(config: _BaseSettings, fields: Set[str], **kwargs: object):
    json_output = config.json(include=fields, indent=2, **kwargs)
    config.config_file.write_text(json_output, encoding='utf-8')


def _read_config(config: _BaseSettings, missing_ok: bool = False):
    try:
        return json.loads(config.config_file.read_bytes())
    except FileNotFoundError:
        if missing_ok:
            default_config: dict[str, Any] = {}
            return default_config
        raise


def _customise_sources(
    init_settings: SettingsSourceCallable,
    env_settings: SettingsSourceCallable,
    file_secret_settings: SettingsSourceCallable,
):
    # Prioritise env vars
    return (env_settings, init_settings)


class _BaseSettings(
    BaseSettings,
    env_prefix='INSTAWOW_',
    env_nested_delimiter='__',
    customise_sources=_customise_sources,
):
    @property
    def config_file(self) -> Path:
        raise NotImplementedError


class _AccessTokens(BaseModel):
    github: typing.Optional[SecretStr] = None
    wago: typing.Optional[SecretStr] = None
    cfcore: typing.Optional[SecretStr] = None


def _encode_reveal_secret_str(value: object):
    if isinstance(value, BaseModel):
        return value.dict()
    elif isinstance(value, SecretStr):
        return value.get_secret_value()
    raise TypeError('Unencodable value', value)


class GlobalConfig(_BaseSettings):
    config_dir: Path = Field(default_factory=lambda: Path(click.get_app_dir('instawow')))
    temp_dir: Path = Field(default_factory=lambda: Path(gettempdir(), 'instawow'))
    auto_update_check: bool = True
    access_tokens: _AccessTokens = _AccessTokens()

    @validator('config_dir', 'temp_dir')
    def _expand_path(cls, value: Path) -> Path:
        return _expand_path(value)

    def list_profiles(self) -> list[str]:
        "Get the names of the profiles contained in ``config_dir``."
        profiles = [c.parent.name for c in self.config_dir.glob('profiles/*/config.json')]
        return profiles

    @classmethod
    def read(cls) -> GlobalConfig:
        dummy_config = cls()
        maybe_config_values = _read_config(dummy_config, missing_ok=True)
        return cls(**maybe_config_values) if maybe_config_values is not None else dummy_config

    def ensure_dirs(self) -> GlobalConfig:
        _ensure_dirs(
            [
                self.config_dir,
                self.temp_dir,
                self.cache_dir,
            ]
        )
        return self

    def write(self) -> GlobalConfig:
        """Write the configuration on disk.

        ``write`` should only be called when configuring instawow.
        This means that environment overrides should only be persisted
        if made during configuration.
        """
        self.ensure_dirs()
        _write_config(
            self, {'auto_update_check', 'access_tokens'}, encoder=_encode_reveal_secret_str
        )
        return self

    @property
    def cache_dir(self) -> Path:
        return self.temp_dir / 'cache'

    @property
    def config_file(self) -> Path:
        return self.config_dir / 'config.json'


class Config(_BaseSettings):
    global_config: GlobalConfig
    profile: str = Field(min_length=1, strip_whitespace=True)
    addon_dir: Path
    game_flavour: Flavour

    @validator('addon_dir')
    def _validate_path_is_writable_dir(cls, value: Path) -> Path:
        value = _expand_path(value)
        if not _is_writable_dir(value):
            raise _PathNotWritableDirectoryError(path=value)
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
    def read(cls, global_config: GlobalConfig | None, profile: str) -> Config:
        if global_config is None:
            global_config = GlobalConfig.read()
        dummy_config = cls.construct(global_config=global_config, profile=profile)
        config = cls(global_config=global_config, **_read_config(dummy_config))
        return config

    def ensure_dirs(self) -> Config:
        _ensure_dirs(
            [
                self.profile_dir,
                self.logging_dir,
                self.plugin_dir,
            ]
        )
        return self

    def write(self) -> Config:
        self.ensure_dirs()
        _write_config(self, {'addon_dir', 'game_flavour', 'profile'})
        return self

    def delete(self) -> None:
        trash((self.profile_dir,), dest=self.global_config.temp_dir, missing_ok=True)

    @property
    def profile_dir(self) -> Path:
        return self.global_config.config_dir / 'profiles' / self.profile

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


def _patch_loguru_enqueue():
    import queue
    import threading
    from types import SimpleNamespace

    import loguru._handler

    # On some systems when instantiating multiprocessing constructs Python
    # starts the multiprocessing resource monitor.  This is done in a subprocess
    # with ``sys.executable`` as the first argument.  In briefcase
    # this points to the same executable that starts the app - there
    # isn't a separate Python executable.  So with every new resource
    # monitor that spawns so does a new copy of the app, ad infinitum.
    # Even when not using briefcase spawning a subprocess slows down start-up,
    # not least because it imports a second copy of the ``site`` module.
    # We replace these multiprocessing constructs with their threading
    # equivalents in loguru since loguru itself does not spawn a subprocesses
    # but creates a separate thread for its "enqueued" logger and we don't
    # use multiprocessing in instawow.
    # This will definitely not come back to bite us.
    setattr(
        loguru._handler,
        'multiprocessing',
        SimpleNamespace(SimpleQueue=queue.Queue, Event=threading.Event, Lock=threading.Lock),
    )


def _intercept_logging_module_calls(log_level: str):  # pragma: no cover
    import logging

    class InterceptHandler(logging.Handler):
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


def setup_logging(logging_dir: Path, log_level: str = 'INFO') -> None:
    debug = log_level == 'DEBUG'
    if debug:
        _intercept_logging_module_calls(log_level)

    _patch_loguru_enqueue()

    values = {
        'level': log_level,
        'enqueue': True,
    }
    logger.configure(
        handlers=[
            {
                **values,
                'sink': logging_dir / 'error.log',
                'rotation': '5 MB',
                'retention': 5,  # Number of log files to keep
            },
        ]
    )
    if debug:
        logger.add(
            **values,
            sink=sys.stderr,
            format='<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | '
            '<level>{level: <8}</level> | '
            '<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan>\n'
            '  <level>{message}</level>',
        )
