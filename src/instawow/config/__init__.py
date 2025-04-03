from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Mapping, Sized
from functools import lru_cache, partial
from pathlib import Path
from typing import NewType, Self, TypeVar

import attrs

from .. import NAME
from .._utils.attrs import enrich_validator_exc, fauxfrozen
from .._utils.file import trash
from ..wow_installations import Flavour, get_installation_dir_from_addon_dir
from ._helpers import (
    FieldMetadata,
    ensure_dirs,
    make_config_converter,
    read_config,
    read_env_vars,
    write_config,
)
from ._helpers import UninitialisedConfigError as UninitialisedConfigError
from ._helpers import config_converter as config_converter

_TSized = TypeVar('_TSized', bound=Sized)


SecretStr = NewType('SecretStr', str)


def _expand_path(value: os.PathLike[str]):
    return Path(value).expanduser().resolve()


def _is_writable_dir(value: Path):
    return value.is_dir() and os.access(value, os.W_OK)


@enrich_validator_exc
def _validate_path_is_writable_dir(_model: object, _attr: attrs.Attribute[Path], value: Path):
    if not _is_writable_dir(value):
        raise ValueError(f'"{value}" is not a writable directory')


def _make_validate_min_length(min_length: int):
    @enrich_validator_exc
    def _validate_min_length(_model: object, _attr: attrs.Attribute[_TSized], value: _TSized):
        if len(value) < min_length:
            raise ValueError(f'Value must have a minimum length of {min_length}')

    return _validate_min_length


@lru_cache(1)
def _make_display_converter():
    converter = make_config_converter()

    @partial(converter.register_unstructure_hook, GlobalConfig)
    def _(global_config: GlobalConfig):
        return converter.unstructure_attrs_asdict(global_config) | {
            'profiles': list(global_config.iter_profiles())
        }

    @partial(converter.register_unstructure_hook, SecretStr)
    def _(value: str):
        return '*' * 10

    return converter


def _get_default_config_dir():
    parent_dir = os.environ.get('XDG_CONFIG_HOME')

    if not parent_dir:
        if sys.platform == 'darwin':
            parent_dir = Path.home() / 'Library' / 'Application Support'
        elif sys.platform == 'win32':
            parent_dir = os.environ.get('APPDATA')

    if not parent_dir:
        parent_dir = Path.home() / '.config'

    return Path(parent_dir, NAME)


def _get_default_cache_dir():
    parent_dir = os.environ.get('XDG_CACHE_HOME')

    if not parent_dir:
        if sys.platform == 'darwin':
            parent_dir = Path.home() / 'Library' / 'Caches'
        elif sys.platform == 'win32':
            parent_dir = os.environ.get('LOCALAPPDATA')

    if not parent_dir:
        parent_dir = Path.home() / '.cache'

    return Path(parent_dir, NAME)


def _get_default_state_dir():
    parent_dir = os.environ.get('XDG_STATE_HOME')

    if not parent_dir and sys.platform not in {'darwin', 'win32'}:
        parent_dir = Path.home() / '.local' / 'state'

    if not parent_dir:
        return _get_default_config_dir()

    return Path(parent_dir, NAME)


@fauxfrozen
class _AccessTokens:
    cfcore: SecretStr | None = attrs.field(
        default=None,
        metadata=FieldMetadata(store=True),
    )
    github: SecretStr | None = attrs.field(
        default=None,
        metadata=FieldMetadata(store=True),
    )


@fauxfrozen
class GlobalConfig:
    config_dir: Path = attrs.field(
        factory=_get_default_config_dir,
        converter=_expand_path,
        metadata=FieldMetadata(env=NAME),
    )
    cache_dir: Path = attrs.field(
        factory=_get_default_cache_dir,
        converter=_expand_path,
        metadata=FieldMetadata(env=NAME),
    )
    state_dir: Path = attrs.field(
        factory=_get_default_state_dir,
        converter=_expand_path,
        metadata=FieldMetadata(env=NAME),
    )
    auto_update_check: bool = attrs.field(
        default=True,
        metadata=FieldMetadata(env=NAME, preparse_from_env=True, store=True),
    )
    access_tokens: _AccessTokens = attrs.field(
        default=_AccessTokens(),
        metadata=FieldMetadata(env=NAME, preparse_from_env=True, store=True),
    )

    @classmethod
    def from_values(cls, values: Mapping[str, object] = {}, *, env: bool = False) -> Self:
        if env:
            values = read_env_vars(cls, values)
        return config_converter.structure(values, cls)

    @classmethod
    def read(cls, env: bool = True) -> Self:
        unsaved_config = cls.from_values(env=env)
        config_values = read_config(cls, unsaved_config.config_file, missing_ok=True)
        return cls.from_values(config_values, env=env) if config_values else unsaved_config

    def iter_profiles(self) -> Iterator[str]:
        "Get the names of the profiles contained in ``config_dir``."
        yield from (c.parent.name for c in self.profiles_config_dir.glob('*/config.json'))

    def iter_installations(self) -> Iterator[Path]:
        """Get the installation directory of each profile, where one can be extracted.

        *instawow* does not mandate that an add-on directory is tied to an installation
        directory which allows to e.g. update add-ons out of band.
        """
        for config_json in self.profiles_config_dir.glob('*/config.json'):
            addon_dir = read_config(ProfileConfig, config_json)['addon_dir']
            maybe_installation_dir = get_installation_dir_from_addon_dir(addon_dir)
            if maybe_installation_dir:
                yield maybe_installation_dir

    def ensure_dirs(self) -> Self:
        ensure_dirs(
            [
                self.config_dir,
                self.cache_dir,
                self.state_dir,
                self.logging_dir,
                self.http_cache_dir,
                self.install_cache_dir,
            ]
        )
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        write_config(self, self.config_file)
        return self

    @property
    def logging_dir(self) -> Path:
        return self.state_dir / 'logs'

    @property
    def http_cache_dir(self) -> Path:
        return self.cache_dir / '_http'

    @property
    def install_cache_dir(self) -> Path:
        return self.cache_dir / '_install'

    @property
    def plugins_cache_dir(self) -> Path:
        return self.cache_dir / 'plugins'

    @property
    def config_file(self) -> Path:
        return self.config_dir / 'config.json'

    @property
    def plugins_config_dir(self) -> Path:
        return self.config_dir / 'plugins'

    @property
    def plugins_state_dir(self) -> Path:
        return self.state_dir / 'plugins'

    @property
    def profiles_config_dir(self) -> Path:
        return self.config_dir / 'profiles'

    @property
    def profiles_state_dir(self) -> Path:
        return self.state_dir / 'profiles'


@fauxfrozen
class _ProfileConfigStub:
    global_config: GlobalConfig
    profile: str = attrs.field(
        converter=str.strip,
        validator=_make_validate_min_length(1),
        metadata=FieldMetadata(env=NAME, store=True),
    )

    @property
    def config_dir(self) -> Path:
        return self.global_config.profiles_config_dir / self.profile

    @property
    def state_dir(self) -> Path:
        return self.global_config.profiles_state_dir / self.profile

    @property
    def config_file(self) -> Path:
        return self.config_dir / 'config.json'

    @property
    def db_file(self) -> Path:
        return self.config_dir / 'db.sqlite'


@fauxfrozen
class ProfileConfig(_ProfileConfigStub):
    addon_dir: Path = attrs.field(
        converter=_expand_path,
        validator=_validate_path_is_writable_dir,
        metadata=FieldMetadata(env=NAME, store=True),
    )
    game_flavour: Flavour = attrs.field(
        metadata=FieldMetadata(env=NAME, store=True),
    )

    @classmethod
    def from_values(cls, values: Mapping[str, object] = {}, *, env: bool = False) -> Self:
        if env:
            values = read_env_vars(cls, values)
        return config_converter.structure(values, cls)

    @classmethod
    def read(cls, global_config: GlobalConfig, profile: str, *, env: bool = True) -> Self:
        return cls.from_values(
            {
                **read_config(cls, _ProfileConfigStub(global_config, profile).config_file),
                'global_config': global_config,
            },
            env=env,
        )

    def unstructure_for_display(self) -> str:
        return _make_display_converter().unstructure(self)

    def ensure_dirs(self) -> Self:
        ensure_dirs(
            [
                self.config_dir,
                self.state_dir,
            ]
        )
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        write_config(self, self.config_file)
        return self

    def delete(self) -> None:
        trash((self.config_dir,))
