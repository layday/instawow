from __future__ import annotations

import contextvars as cv
from collections.abc import Callable
from contextlib import AbstractContextManager
from itertools import chain
from typing import Self

from . import _sources, pkg_db, plugins
from . import config as _config
from . import resolvers as _resolvers
from ._utils.attrs import fauxfrozen

_config_party_var: cv.ContextVar[ConfigParty | Callable[[], _config.ProfileConfig]] = (
    cv.ContextVar('_config_party_var')
)


@fauxfrozen
class ConfigParty:
    config: _config.ProfileConfig
    database: AbstractContextManager[pkg_db.Connection]
    resolvers: _resolvers.Resolvers

    @classmethod
    def from_config(cls, config: _config.ProfileConfig) -> Self:
        return cls(config, _ReentrantDatabaseHandle(), _make_resolvers())


class _ReentrantDatabaseHandle(AbstractContextManager['pkg_db.Connection']):
    def __init__(self) -> None:
        self._connection = None
        self._referent_count = 0

    def __enter__(self) -> pkg_db.Connection:
        if self._connection is None:
            self._connection = pkg_db.prepare_database(config().db_file_path)
        self._referent_count += 1
        return self._connection

    def __exit__(self, *_: object) -> None:
        self._referent_count -= 1
        if self._referent_count == 0 and self._connection is not None:
            self._connection.close()
            self._connection = None


def _make_resolvers():
    return _resolvers.Resolvers(
        r() if callable(r) else r
        for r in chain(
            (r for g in plugins.get_plugin_resolvers() for r in g),
            _sources.DEFAULT_RESOLVERS,
        )
    )


def _get_config_party():
    config_party = _config_party_var.get()
    if callable(config_party):
        config_party = ConfigParty.from_config(config_party())
        _config_party_var.set(config_party)
    return config_party


@object.__new__
class config:
    def __call__(self) -> _config.ProfileConfig:
        return _get_config_party().config

    set = staticmethod(_config_party_var.set)
    reset = staticmethod(_config_party_var.reset)


def database() -> AbstractContextManager[pkg_db.Connection]:
    return _get_config_party().database


def resolvers() -> _resolvers.Resolvers:
    return _get_config_party().resolvers
