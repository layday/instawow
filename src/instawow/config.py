from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Iterable, Mapping, Sized
from functools import lru_cache, partial
from pathlib import Path
from tempfile import gettempdir
from typing import Any, TypedDict, TypeVar

import cattrs.preconf.json
from attrs import Attribute, field, fields, frozen, has
from cattrs import AttributeValidationNote, Converter
from cattrs.gen import make_dict_unstructure_fn, override
from typing_extensions import Self

from .common import Flavour
from .utils import add_exc_note, trash

_T = TypeVar('_T')

_MISSING = object()

_BOTTOM_DIR_NAME = 'instawow'


class SecretStr(str):
    pass


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
            add_exc_note(exc, AttributeValidationNote(note, attr.name, attr.type))
            raise

    return wrapper


@_enrich_validator_exc
def _validate_path_is_writable_dir(_model: object, _attr: Attribute[Path], value: Path):
    if not _is_writable_dir(value):
        raise ValueError(f'"{value}" is not a writable directory')


def _make_validate_min_length(min_length: int):
    @_enrich_validator_exc
    def _validate_min_length(_model: object, _attr: Attribute[Sized], value: Sized):
        if len(value) < min_length:
            raise ValueError(f'Value must have a minimum length of {min_length}')

    return _validate_min_length


def _encode_config_for_display(config: object):
    converter = _make_display_converter()
    return json.dumps(
        converter.unstructure(config),
        indent=2,
    )


def _write_config(config: object, config_path: Path):
    converter = _make_write_converter()
    config_path.write_text(
        json.dumps(converter.unstructure(config), indent=2),
        encoding='utf-8',
    )


def _read_config(config_path: Path, missing_ok: bool = False) -> dict[str, Any]:
    try:
        return json.loads(config_path.read_bytes())
    except FileNotFoundError:
        if missing_ok:
            return {}
        raise


def _compute_var(field_: Attribute[object], default: object):
    if not field_.metadata.get('from_env'):
        return default

    value = os.environ.get(f'instawow_{field_.name}'.upper())
    if value is None:
        return default
    elif field_.metadata.get('as_json'):
        return json.loads(value)
    else:
        return value


def _read_env_vars(config_cls: Any, values: Mapping[str, object]):
    return {
        f.name: v
        for f in fields(config_cls)
        for v in (_compute_var(f, values.get(f.name, _MISSING)),)
        if v is not _MISSING
    }


def _make_attrs_instance_hook_factory(converter: Converter, type_: type[Any]):
    "Allow passing in a structured attrs instance to ``structure``."
    structure = converter.gen_structure_attrs_fromdict(type_)

    def structure_wrapper(value: Mapping[str, Any], type_: type[Any]):
        return value if isinstance(value, type_) else structure(value, type_)

    return structure_wrapper


def make_config_converter():
    converter = Converter()
    cattrs.preconf.json.configure_converter(converter)
    converter.register_structure_hook(Path, lambda v, _: Path(v))
    converter.register_unstructure_hook(Path, str)
    return converter


@lru_cache(1)
def _make_display_converter():
    def convert_secret_string(value: str):
        return '**********'

    def convert_global_config(global_config: GlobalConfig):
        return converter.unstructure_attrs_asdict(global_config) | {
            'profiles': global_config.list_profiles()
        }

    converter = make_config_converter()
    converter.register_unstructure_hook(GlobalConfig, convert_global_config)
    converter.register_unstructure_hook(SecretStr, convert_secret_string)
    return converter


@lru_cache(1)
def _make_write_converter():
    converter = make_config_converter()
    for config_cls in [GlobalConfig, Config]:
        converter.register_unstructure_hook(
            config_cls,
            make_dict_unstructure_fn(
                config_cls,
                converter,
                **{  # pyright: ignore[reportArgumentType]  # See microsoft/pyright#5255
                    f.name: override(omit=True)
                    for f in fields(config_cls)
                    if not f.metadata.get('write_on_disk')
                },
            ),
        )
    return converter


def _get_default_config_dir():
    config_parent_dir = os.environ.get('XDG_CONFIG_HOME')

    if not config_parent_dir:
        if sys.platform == 'darwin':
            config_parent_dir = Path.home() / 'Library' / 'Application Support'
        elif sys.platform == 'win32':
            config_parent_dir = os.environ.get('APPDATA')

    if not config_parent_dir:
        config_parent_dir = Path.home() / '.config'

    return Path(config_parent_dir, _BOTTOM_DIR_NAME)


def _get_default_temp_dir():
    return Path(gettempdir(), f'{_BOTTOM_DIR_NAME}t')


def _get_default_state_dir():
    state_parent_dir = os.environ.get('XDG_STATE_HOME')

    if not state_parent_dir and sys.platform not in {'darwin', 'win32'}:
        state_parent_dir = Path.home() / '.local' / 'state'

    if not state_parent_dir:
        return _get_default_config_dir()

    return Path(state_parent_dir, _BOTTOM_DIR_NAME)


class _ConfigMetadata(TypedDict, total=False):
    from_env: bool
    as_json: bool
    write_on_disk: bool


_AccessToken = SecretStr | None


@frozen
class _AccessTokens:
    cfcore: _AccessToken = None
    github: _AccessToken = None
    wago: _AccessToken = None
    wago_addons: _AccessToken = None


@frozen
class GlobalConfig:
    config_dir: Path = field(
        factory=_get_default_config_dir,
        converter=_expand_path,
        metadata=_ConfigMetadata(from_env=True),
    )
    temp_dir: Path = field(
        factory=_get_default_temp_dir,
        converter=_expand_path,
        metadata=_ConfigMetadata(from_env=True),
    )
    state_dir: Path = field(
        factory=_get_default_state_dir,
        converter=_expand_path,
        metadata=_ConfigMetadata(from_env=True),
    )
    auto_update_check: bool = field(
        default=True,
        metadata=_ConfigMetadata(from_env=True, as_json=True, write_on_disk=True),
    )
    access_tokens: _AccessTokens = field(
        default=_AccessTokens(),
        metadata=_ConfigMetadata(from_env=True, as_json=True, write_on_disk=True),
    )

    @classmethod
    def from_values(cls, values: Mapping[str, object] = {}, *, env: bool = False) -> Self:
        if env:
            values = _read_env_vars(cls, values)
        return config_converter.structure(values, cls)

    @classmethod
    def read(cls) -> Self:
        env_only_config = cls.from_values(env=True)
        config_values = _read_config(env_only_config.config_file, missing_ok=True)
        return cls.from_values(config_values, env=True) if config_values else env_only_config

    def list_profiles(self) -> list[str]:
        "Get the names of the profiles contained in ``config_dir``."
        profiles = [c.parent.name for c in self.profiles_config_dir.glob('*/config.json')]
        return profiles

    def ensure_dirs(self) -> Self:
        _ensure_dirs(
            [
                self.config_dir,
                self.temp_dir,
                self.state_dir,
                self.cache_dir,
                self.http_cache_dir,
                self.install_cache_dir,
            ]
        )
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        _write_config(self, self.config_file)
        return self

    @property
    def cache_dir(self) -> Path:
        return self.temp_dir / 'cache'

    @property
    def http_cache_dir(self) -> Path:
        return self.temp_dir / 'cache' / '_http'

    @property
    def install_cache_dir(self) -> Path:
        return self.temp_dir / 'cache' / '_install'

    @property
    def config_file(self) -> Path:
        return self.config_dir / 'config.json'

    @property
    def profiles_config_dir(self) -> Path:
        return self.config_dir / 'profiles'

    @property
    def profiles_state_dir(self) -> Path:
        return self.state_dir / 'profiles'


@frozen
class Config:
    global_config: GlobalConfig
    profile: str = field(
        converter=str.strip,
        validator=_make_validate_min_length(1),
        metadata=_ConfigMetadata(from_env=True, write_on_disk=True),
    )
    addon_dir: Path = field(
        converter=_expand_path,
        validator=_validate_path_is_writable_dir,
        metadata=_ConfigMetadata(from_env=True, write_on_disk=True),
    )
    game_flavour: Flavour = field(metadata=_ConfigMetadata(from_env=True, write_on_disk=True))

    @classmethod
    def make_dummy_config(cls, **values: object) -> Config:
        return object.__new__(type(f'Dummy{cls.__name__}', (cls,), values))

    @classmethod
    def from_values(cls, values: Mapping[str, object] = {}, *, env: bool = False) -> Self:
        if env:
            values = _read_env_vars(cls, values)
        return config_converter.structure(values, cls)

    @classmethod
    def read(cls, global_config: GlobalConfig, profile: str) -> Self:
        dummy_config = cls.make_dummy_config(global_config=global_config, profile=profile)
        return cls.from_values(
            {**_read_config(dummy_config.config_file), 'global_config': global_config},
            env=True,
        )

    def encode_for_display(self) -> str:
        return _encode_config_for_display(self)

    def ensure_dirs(self) -> Self:
        _ensure_dirs(
            [
                self.config_dir,
                self.state_dir,
                self.logging_dir,
                self.plugins_dir,
            ]
        )
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        _write_config(self, self.config_file)
        return self

    def delete(self) -> None:
        trash((self.config_dir,), dest=self.global_config.temp_dir, missing_ok=True)

    @property
    def config_dir(self) -> Path:
        return self.global_config.profiles_config_dir / self.profile

    @property
    def state_dir(self) -> Path:
        return self.global_config.profiles_state_dir / self.profile

    @property
    def logging_dir(self) -> Path:
        return self.state_dir / 'logs'

    @property
    def plugins_dir(self) -> Path:
        return self.state_dir / 'plugins'

    @property
    def config_file(self) -> Path:
        return self.config_dir / 'config.json'

    @property
    def db_uri(self) -> str:
        return f"sqlite:///{self.config_dir / 'db.sqlite'}"


config_converter = make_config_converter()
config_converter.register_structure_hook_factory(
    has, partial(_make_attrs_instance_hook_factory, config_converter)
)
