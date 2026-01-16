from __future__ import annotations

import contextvars as cv
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from functools import cached_property
from itertools import chain
from pathlib import Path
from typing import Self

from . import _sources, definitions, pkg_db, plugins
from . import config as _config
from . import resolvers as _resolvers
from ._utils.attrs import fauxfrozen
from .results import AnyResult, PkgSourceDisabled, PkgSourceInvalid, resultify

_config_party_var: cv.ContextVar[ConfigParty | Callable[[], _config.ProfileConfig]] = (
    cv.ContextVar('_config_party_var')
)


class _Resolvers(dict[str, '_resolvers.Resolver']):
    def __init__(self, resolvers: Iterable[_resolvers.Resolver]):
        super().__init__((r.metadata.id, r) for r in resolvers)

    def get_or_dummy(self, key: str) -> _resolvers.Resolver:
        if key in self.disabled_resolver_reasons:
            error = PkgSourceDisabled(self.disabled_resolver_reasons[key])
        elif key in self:
            return self[key]
        else:
            error = PkgSourceInvalid()

        @object.__new__
        class DummyResolver(_resolvers.Resolver):
            async def resolve(
                self, defns: Sequence[definitions.Defn]
            ) -> dict[definitions.Defn, AnyResult[_resolvers.PkgCandidate]]:
                return dict.fromkeys(defns, error)

            async def get_changelog(self, url: str):
                raise error

            def __getattr__(self, name: str):
                raise error

        return DummyResolver

    @cached_property
    def addon_toc_key_and_id_pairs(self) -> Collection[tuple[str, str]]:
        return [
            (r.metadata.addon_toc_key, r.metadata.id)
            for r in self.values()
            if r.metadata.addon_toc_key
        ]

    @cached_property
    def disabled_resolver_reasons(self) -> Mapping[str, str]:
        return {r.metadata.id: d for r in self.values() for d in (r.get_disabled_reason(),) if d}

    @cached_property
    def pkg_downloaders(self) -> _ResolverPkgDownloaders:
        return _ResolverPkgDownloaders(self)

    @cached_property
    def priorities(self) -> _ResolverPriorities:
        return _ResolverPriorities(self)


class _ResolverPkgDownloaders(
    dict[str, Callable[[definitions.Defn, str], Awaitable[AnyResult[Path]]]]
):
    def __init__(self, resolvers: _Resolvers) -> None:
        self.__resolvers = resolvers

    def __missing__(self, key: str):
        downloader = self[key] = resultify(self.__resolvers[key].download_pkg_archive)
        return downloader


class _ResolverPriorities(dict[str, float]):
    def __init__(self, resolvers: _Resolvers) -> None:
        super().__init__((n, i) for i, n in enumerate(resolvers))

    def __missing__(self, key: str) -> float:
        return float('inf')


def _make_resolvers():
    return _Resolvers(
        r() if callable(r) else r
        for r in chain(
            (r for g in plugins.get_plugin_resolvers() for r in g),
            _sources.DEFAULT_RESOLVERS,
        )
    )


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


@fauxfrozen
class ConfigParty:
    config: _config.ProfileConfig
    database: AbstractContextManager[pkg_db.Connection]
    resolvers: _Resolvers

    @classmethod
    def from_config(cls, config: _config.ProfileConfig) -> Self:
        return cls(config, _ReentrantDatabaseHandle(), _make_resolvers())


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


def resolvers() -> _Resolvers:
    return _get_config_party().resolvers
