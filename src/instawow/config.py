from __future__ import annotations

from collections.abc import Callable, Iterable, Set, Sized
import json
import os
from pathlib import Path
import sys
from tempfile import gettempdir
import typing
from typing import Any, TypeVar

from attrs import Attribute, field, fields, frozen, has, resolve_types
from cattrs import GenConverter
from cattrs.gen import make_dict_unstructure_fn, override  # pyright: ignore
from cattrs.preconf.json import configure_converter
import click
from loguru import logger
from typing_extensions import Self

from .common import Flavour
from .utils import trash

_T = TypeVar('_T')

_MISSING = object()


class SecretStr(str):
    pass


def _convert_secret_string(value: str):
    return '**********' if value else ''


def _expand_path(value: Path):
    return Path(os.path.abspath(os.path.expanduser(value)))


def _is_writable_dir(value: Path):
    return value.is_dir() and os.access(value, os.W_OK)


def _ensure_dirs(dirs: Iterable[Path]):
    for dir_ in dirs:
        dir_.mkdir(exist_ok=True, parents=True)


def _enrich_validator_exc(validator: Callable[[object, Attribute[_T], _T], None]):
    def wrapper(model: object, attr: Attribute[_T], value: _T):
        try:
            validator(model, attr, value)
        except BaseException as exc:
            note = f'Structuring class {model.__class__.__name__} @ attribute {attr.name}'
            exc.__note__ = note  # pyright: ignore
            raise exc

    return wrapper


@_enrich_validator_exc
def _validate_path_is_writable_dir(model: object, attr: Attribute[Path], value: Path):
    if not _is_writable_dir(value):
        raise ValueError(f'"{value}" is not a writable directory')


def _make_validate_min_length(min_length: int):
    @_enrich_validator_exc
    def _validate_min_length(model: object, attr: Attribute[Sized], value: Sized):
        if len(value) < min_length:
            raise ValueError(f'value must have a minimum length of {min_length}')

    return _validate_min_length


def _encode_config_for_display(config: object):
    converter = make_config_converter()
    converter.register_unstructure_hook(SecretStr, _convert_secret_string)
    return json.dumps(
        converter.unstructure(config),  # pyright: ignore[reportUnknownMemberType]
        indent=2,
    )


def _write_config(config: object, config_path: Path, fields_to_include: Set[str]):
    config_cls = config.__class__
    converter = make_config_converter()
    converter.register_unstructure_hook(
        config_cls,
        make_dict_unstructure_fn(  # pyright: ignore
            config_cls,
            converter,
            **{
                f.name: override(omit=True)
                for f in fields(config_cls)
                if f.name not in fields_to_include
            },
        ),
    )
    config_path.write_text(
        json.dumps(
            converter.unstructure(config), indent=2  # pyright: ignore[reportUnknownMemberType]
        ),
        encoding='utf-8',
    )


def _read_config(config_path: Path, missing_ok: bool = False):
    try:
        return json.loads(config_path.read_bytes())
    except FileNotFoundError:
        if missing_ok:
            default_config: dict[str, Any] = {}
            return default_config
        raise


def _compute_var(field: Attribute[object], default: object):
    if not field.metadata.get('env'):
        return default

    value = os.environ.get(f'instawow_{field.name}'.upper())
    if value is None:
        return default
    elif field.metadata.get('as_json'):
        return json.loads(value)
    else:
        return value


def _read_env_vars(config_cls: type, **values: object):
    return {
        f.name: v
        for f in fields(config_cls)
        for v in (_compute_var(f, values.get(f.name, _MISSING)),)
        if v is not _MISSING
    }


def make_config_converter():
    converter = GenConverter()
    configure_converter(converter)
    converter.register_structure_hook(Path, lambda v, _: Path(v))
    converter.register_unstructure_hook(Path, str)
    return converter


@frozen
class _AccessTokens:
    github: typing.Optional[SecretStr] = None
    wago: typing.Optional[SecretStr] = None
    cfcore: typing.Optional[SecretStr] = None


@frozen
class GlobalConfig:
    config_dir: Path = field(
        factory=lambda: Path(click.get_app_dir('instawow')),
        converter=_expand_path,
        metadata={'env': True},
    )
    temp_dir: Path = field(
        factory=lambda: Path(gettempdir(), 'instawow'),
        converter=_expand_path,
        metadata={'env': True},
    )
    auto_update_check: bool = field(
        default=True,
        metadata={'env': True, 'as_json': True},
    )
    access_tokens: _AccessTokens = field(
        default=_AccessTokens(),
        metadata={'env': True, 'as_json': True},
    )

    @classmethod
    def from_env(cls, **values: object) -> Self:
        return config_converter.structure(_read_env_vars(cls, **values), cls)

    @classmethod
    def read(cls) -> Self:
        env_only_config = cls.from_env()
        config_values = _read_config(env_only_config.config_file, missing_ok=True)
        return cls.from_env(**config_values) if config_values is not None else env_only_config

    def list_profiles(self) -> list[str]:
        "Get the names of the profiles contained in ``config_dir``."
        profiles = [c.parent.name for c in self.config_dir.glob('profiles/*/config.json')]
        return profiles

    def ensure_dirs(self) -> Self:
        _ensure_dirs(
            [
                self.config_dir,
                self.temp_dir,
                self.cache_dir,
            ]
        )
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        _write_config(self, self.config_file, {'auto_update_check', 'access_tokens'})
        return self

    @property
    def cache_dir(self) -> Path:
        return self.temp_dir / 'cache'

    @property
    def config_file(self) -> Path:
        return self.config_dir / 'config.json'


@frozen
class Config:
    global_config: GlobalConfig
    profile: str = field(
        converter=lambda v: v.strip(),
        validator=_make_validate_min_length(1),
        metadata={'env': True},
    )
    addon_dir: Path = field(
        converter=_expand_path,
        validator=_validate_path_is_writable_dir,
        metadata={'env': True},
    )
    game_flavour: Flavour = field(metadata={'env': True})

    @classmethod
    def make_dummy_config(cls, **values: object) -> Self:
        return object.__new__(type(f'Dummy{cls.__name__}', (cls,), values))

    @classmethod
    def from_env(cls, **values: object) -> Self:
        return config_converter.structure(_read_env_vars(cls, **values), cls)

    @classmethod
    def read(cls, global_config: GlobalConfig, profile: str) -> Self:
        dummy_config = cls.make_dummy_config(global_config=global_config, profile=profile)
        return cls.from_env(
            **{**_read_config(dummy_config.config_file), 'global_config': global_config}
        )

    def encode_for_display(self) -> str:
        return _encode_config_for_display(self)

    def ensure_dirs(self) -> Self:
        _ensure_dirs(
            [
                self.profile_dir,
                self.logging_dir,
                self.plugin_dir,
            ]
        )
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        _write_config(self, self.config_file, {'addon_dir', 'game_flavour', 'profile'})
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
    def db_uri(self) -> str:
        return f"sqlite:///{self.profile_dir / 'db.sqlite'}"


config_converter = make_config_converter()
config_converter.register_structure_hook_func(
    has,
    lambda c, t: (
        c if isinstance(c, t) else config_converter.structure_attrs_fromdict(c, resolve_types(t))
    ),
)


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


def setup_logging(logging_dir: Path, debug: bool) -> None:
    log_level = 'DEBUG' if debug else 'INFO'

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
