from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from pathlib import Path
from typing import Self

from attrs import field

from instawow._utils.attrs import fauxfrozen
from instawow.config import Dirs, ProfileConfig, SecretStr, config_converter, make_plugin_dirs
from instawow.config._helpers import (
    FieldMetadata,
    ensure_dirs,
    read_config,
    read_env_vars,
    write_config,
)

from . import NAME


@fauxfrozen(kw_only=True)
class _AccessTokens:
    wago: SecretStr | None = field(
        default=None, metadata=FieldMetadata(env_prefix=True, store=True)
    )


@fauxfrozen(kw_only=True)
class PluginConfig:
    profile_config: ProfileConfig
    access_tokens: _AccessTokens = field(
        default=_AccessTokens(), metadata=FieldMetadata(env_prefix=NAME, store=True)
    )
    dirs: Dirs = field(factory=partial(make_plugin_dirs, NAME), init=False)

    @classmethod
    def from_values(cls, values: Mapping[str, object] = {}, *, env: bool = False) -> Self:
        if env:
            values = read_env_vars(cls, values)
        return config_converter.structure(values, cls)

    @classmethod
    def read(cls, profile_config: ProfileConfig, *, env: bool = True) -> Self:
        return cls.from_values(
            read_config(cls, cls(profile_config=profile_config).config_file_path, missing_ok=True)
            | {'profile_config': profile_config},
            env=env,
        )

    def ensure_dirs(self) -> Self:
        ensure_dirs(
            self.dirs.config,
            self.profile_cache_path,
        )
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        write_config(self, self.config_file_path)
        return self

    @property
    def profile_cache_path(self) -> Path:
        return self.dirs.cache / 'profiles' / self.profile_config.profile

    @property
    def config_file_path(self) -> Path:
        return self.dirs.config / 'config.json'
