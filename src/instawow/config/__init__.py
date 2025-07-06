from __future__ import annotations

import os
from collections.abc import Iterator, Mapping, Sized
from functools import partial
from pathlib import Path
from typing import Self

import attrs
from attrs import field

from .. import NAME
from .._utils.attrs import enrich_validator_exc, fauxfrozen
from .._utils.file import expand_path, trash
from ..wow_installations import Track, extract_installation_dir_from_addon_dir
from ._dirs import get_cache_dir, get_config_dir, get_state_dir
from ._helpers import (
    FieldMetadata,
    SecretStr,
    ensure_dirs,
    read_config,
    read_env_vars,
    write_config,
)
from ._helpers import UninitialisedConfigError as UninitialisedConfigError
from ._helpers import config_converter as config_converter

_path_field = partial(field, converter=expand_path)


@enrich_validator_exc
def _validate_path_is_writable_dir(_model: object, _attr: attrs.Attribute[Path], value: Path):
    if not (value.is_dir() and os.access(value, os.W_OK)):
        raise ValueError(f'"{value}" is not a writable directory')


def _make_validate_min_length(min_length: int):
    @enrich_validator_exc
    def _validate_min_length[SizedT: Sized](
        _model: object, _attr: attrs.Attribute[SizedT], value: SizedT
    ):
        if len(value) < min_length:
            raise ValueError(f'Value must have a minimum length of {min_length}')

    return _validate_min_length


@fauxfrozen(kw_only=True)
class _AccessTokens:
    cfcore: SecretStr | None = field(
        default=None,
        metadata=FieldMetadata(env_prefix=True, store=True),
    )
    github: SecretStr | None = field(
        default=None,
        metadata=FieldMetadata(env_prefix=True, store=True),
    )
    wago_addons: SecretStr | None = field(
        default=None,
        metadata=FieldMetadata(env_prefix=True, store=True),
    )


@fauxfrozen(kw_only=True)
class Dirs:
    cache: Path = _path_field()
    config: Path = _path_field()
    state: Path = _path_field()


def _make_default_dirs() -> Dirs:
    return Dirs(cache=get_cache_dir(), config=get_config_dir(), state=get_state_dir())


def make_plugin_dirs(plugin_name: str) -> Dirs:
    parts = ('plugins', plugin_name)
    return Dirs(
        cache=get_cache_dir(*parts), config=get_config_dir(*parts), state=get_state_dir(*parts)
    )


@fauxfrozen(kw_only=True)
class GlobalConfig:
    auto_update_check: bool = field(
        default=True, metadata=FieldMetadata(env_prefix=NAME, store=True)
    )
    access_tokens: _AccessTokens = field(
        default=_AccessTokens(), metadata=FieldMetadata(env_prefix=NAME, store='independently')
    )
    dirs: Dirs = field(factory=_make_default_dirs, init=False)

    @classmethod
    def from_values(cls, values: Mapping[str, object] = {}, *, env: bool = False) -> Self:
        if env:
            values = read_env_vars(cls, values)
        return config_converter.structure(values, cls)

    @classmethod
    def read(cls, *, env: bool = True) -> Self:
        env_config = cls.from_values(env=env)
        disk_config_values = read_config(cls, env_config.config_file_path, missing_ok=True)
        return cls.from_values(disk_config_values, env=env) if disk_config_values else env_config

    def ensure_dirs(self) -> Self:
        ensure_dirs(*attrs.astuple(self.dirs))
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        write_config(self, self.config_file_path)
        return self

    @property
    def config_file_path(self) -> Path:
        return self.dirs.config / 'config.json'


@fauxfrozen(kw_only=True)
class ProfileConfig:
    global_config: GlobalConfig
    profile: str = field(
        converter=str.strip,
        validator=_make_validate_min_length(1),
        metadata=FieldMetadata(store=True),
    )
    addon_dir: Path = _path_field(
        validator=_validate_path_is_writable_dir, metadata=FieldMetadata(store=True)
    )
    track: Track = field(
        metadata=FieldMetadata(
            store=True,
            store_alias='game_flavour',  # For backward compatibility.
        )
    )

    @classmethod
    def _make_config_file_path(cls, global_config: GlobalConfig, profile: str):
        return global_config.dirs.config / 'profiles' / profile / 'config.json'

    @classmethod
    def from_values(cls, values: Mapping[str, object] = {}, env: bool = False) -> Self:
        if env:
            values = read_env_vars(cls, values)
        return config_converter.structure(values, cls)

    @classmethod
    def read(cls, global_config: GlobalConfig, profile: str, *, env: bool = True) -> Self:
        return cls.from_values(
            read_config(cls, cls._make_config_file_path(global_config, profile))
            | {'global_config': global_config},
            env=env,
        )

    @classmethod
    def iter_profiles(cls, global_config: GlobalConfig) -> Iterator[str]:
        yield from (
            c.parent.name for c in global_config.dirs.config.glob('profiles/*/config.json')
        )

    @classmethod
    def iter_profile_installations(cls, global_config: GlobalConfig) -> Iterator[Path]:
        for config_json in global_config.dirs.config.glob('profiles/*/config.json'):
            addon_dir = read_config(cls, config_json)['addon_dir']
            maybe_installation_dir = extract_installation_dir_from_addon_dir(addon_dir)
            if maybe_installation_dir:
                yield maybe_installation_dir

    def ensure_dirs(self) -> Self:
        ensure_dirs(
            self.config_path,
        )
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        write_config(self, self.config_file_path)
        return self

    def delete(self) -> None:
        trash((self.config_path,))

    @property
    def config_path(self) -> Path:
        return self.config_file_path.parent

    @property
    def config_file_path(self) -> Path:
        return self._make_config_file_path(self.global_config, self.profile)

    @property
    def db_file_path(self) -> Path:
        return self.config_path / 'db.sqlite'
