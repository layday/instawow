from __future__ import annotations

import contextvars as cv
from collections.abc import (
    Collection,
    Mapping,
    Sequence,
)
from contextlib import AbstractAsyncContextManager
from functools import cached_property
from itertools import chain
from typing import TypeAlias

from typing_extensions import Self

from . import http, pkg_db
from ._sources.cfcore import CfCoreResolver
from ._sources.github import GithubResolver
from ._sources.instawow import InstawowResolver
from ._sources.tukui import TukuiResolver
from ._sources.wago import WagoResolver
from ._sources.wowi import WowiResolver
from ._utils.iteration import WeakValueDefaultDictionary
from .config import ProfileConfig
from .pkg_archives import ArchiveOpener, open_zip_archive
from .plugins import get_plugin_resolvers
from .resolvers import Resolver


class _DummyLock:
    async def __aenter__(self):
        pass

    async def __aexit__(self, *args: object):
        pass


class _Resolvers(dict[str, Resolver]):
    @cached_property
    def archive_opener_dict(self) -> _ResolverArchiveOpenerDict:
        return _ResolverArchiveOpenerDict(self)

    @cached_property
    def priority_dict(self) -> _ResolverPriorityDict:
        return _ResolverPriorityDict(self)

    @cached_property
    def addon_toc_key_and_id_pairs(self) -> Collection[tuple[str, str]]:
        return [
            (r.metadata.addon_toc_key, r.metadata.id)
            for r in self.values()
            if r.metadata.addon_toc_key
        ]


class _ResolverArchiveOpenerDict(dict[str, ArchiveOpener]):
    def __init__(self, resolvers: _Resolvers) -> None:
        super().__init__(
            (r.metadata.id, r.archive_opener) for r in resolvers.values() if r.archive_opener
        )

    def __missing__(self, key: str) -> ArchiveOpener:
        return open_zip_archive


class _ResolverPriorityDict(dict[str, float]):
    def __init__(self, resolvers: _Resolvers) -> None:
        super().__init__((n, i) for i, n in enumerate(resolvers))

    def __missing__(self, key: str) -> float:
        return float('inf')


_Locks: TypeAlias = Mapping[object, AbstractAsyncContextManager[None]]

_locks = cv.ContextVar[_Locks]('_locks', default=WeakValueDefaultDictionary(_DummyLock))
_web_client = cv.ContextVar[http.ClientSessionType]('_web_client')


def contextualise(
    *,
    locks: _Locks | None = None,
    web_client: http.ClientSessionType | None = None,
) -> None:
    "Set variables for the current context."
    if locks is not None:
        _locks.set(locks)
    if web_client is not None:
        _web_client.set(web_client)


class ManagerCtx:
    "The one true context."

    RESOLVERS: Sequence[type[Resolver]] = [
        GithubResolver,
        CfCoreResolver,
        WowiResolver,
        TukuiResolver,
        InstawowResolver,
        WagoResolver,
    ]
    'Default resolvers.'

    def __init__(
        self,
        config: ProfileConfig,
    ) -> None:
        self.config: ProfileConfig = config

        builtin_resolver_classes = list(self.RESOLVERS)

        for resolver, access_token in (
            (r, getattr(self.config.global_config.access_tokens, r.requires_access_token, None))
            for r in self.RESOLVERS
            if r.requires_access_token is not None
        ):
            if access_token is None:
                builtin_resolver_classes.remove(resolver)

        resolver_classes = chain(
            (r for g in get_plugin_resolvers() for r in g), builtin_resolver_classes
        )
        self.resolvers: _Resolvers = _Resolvers((r.metadata.id, r(self)) for r in resolver_classes)

        self.database: pkg_db.DatabaseHandle = pkg_db.DatabaseHandle(self.config.db_file)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.database.close()

    @property
    def locks(self) -> _Locks:
        "Lock factory used to synchronise async operations."
        return _locks.get()

    @property
    def web_client(self) -> http.ClientSessionType:
        return _web_client.get()
