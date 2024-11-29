from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Self

import attrs

from instawow._utils.attrs import fauxfrozen
from instawow.config import ProfileConfig, SecretStr, config_converter
from instawow.config._helpers import (
    FieldMetadata,
    ensure_dirs,
    read_config,
    read_env_vars,
    write_config,
)

from . import NAME


@fauxfrozen
class _AccessTokens:
    wago: SecretStr | None = attrs.field(
        default=None,
        metadata=FieldMetadata(store=True),
    )


@fauxfrozen
class PluginConfig:
    profile_config: ProfileConfig
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
    def read(cls, profile_config: ProfileConfig, *, env: bool = True) -> Self:
        dummy_config = object.__new__(
            type(f'Dummy{cls.__name__}', (cls,), {'profile_config': profile_config})
        )
        return cls.from_values(
            {
                **read_config(cls, dummy_config.config_file, missing_ok=True),
                'profile_config': profile_config,
            },
            env=env,
        )

    def ensure_dirs(self) -> Self:
        ensure_dirs(
            [
                self.cache_dir,
                self.config_dir,
                self.profile_cache_dir,
            ]
        )
        return self

    def write(self) -> Self:
        self.ensure_dirs()
        write_config(self, self.config_file)
        return self

    @property
    def cache_dir(self) -> Path:
        return self.profile_config.global_config.plugins_cache_dir / NAME

    @property
    def config_dir(self) -> Path:
        return self.profile_config.global_config.plugins_config_dir / NAME

    @property
    def profile_cache_dir(self) -> Path:
        return self.cache_dir / 'profiles' / self.profile_config.profile

    @property
    def config_file(self) -> Path:
        return self.config_dir / 'config.json'
