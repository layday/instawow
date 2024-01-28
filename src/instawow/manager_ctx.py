from __future__ import annotations

import contextvars as cv
import json
from collections.abc import (
    Collection,
    Mapping,
    Sequence,
)
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from functools import cached_property, lru_cache
from itertools import chain
from typing import TypeAlias

import sqlalchemy as sa
from loguru import logger
from typing_extensions import Self

from . import http, pkg_db
from ._sources.cfcore import CfCoreResolver
from ._sources.github import GithubResolver
from ._sources.instawow import InstawowResolver
from ._sources.tukui import TukuiResolver
from ._sources.wago import WagoResolver
from ._sources.wowi import WowiResolver
from .archives import ArchiveOpener, open_zip_archive
from .catalogue.cataloguer import (
    CATALOGUE_VERSION,
    ComputedCatalogue,
)
from .config import Config
from .http import make_generic_progress_ctx
from .plugins import get_plugin_resolvers
from .resolvers import Resolver
from .utils import (
    WeakValueDefaultDictionary,
    time_op,
)

_LOAD_CATALOGUE_LOCK = '_LOAD_CATALOGUE_'


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


_web_client = cv.ContextVar[http.ClientSessionType]('_web_client')

LocksType: TypeAlias = Mapping[object, AbstractAsyncContextManager[None]]

_locks = cv.ContextVar[LocksType]('_locks', default=WeakValueDefaultDictionary(_DummyLock))


def contextualise(
    *,
    web_client: http.ClientSessionType | None = None,
    locks: LocksType | None = None,
) -> None:
    "Set variables for the current context."
    if web_client is not None:
        _web_client.set(web_client)
    if locks is not None:
        _locks.set(locks)


@lru_cache(1)
def _parse_catalogue(raw_catalogue: bytes):
    with time_op(lambda t: logger.debug(f'parsed catalogue in {t:.3f}s')):
        return ComputedCatalogue.from_base_catalogue(json.loads(raw_catalogue))


class ManagerCtx:
    __slots__ = [
        'config',
        'database',
        'resolvers',
    ]

    RESOLVERS: Sequence[type[Resolver]] = [
        GithubResolver,
        CfCoreResolver,
        WowiResolver,
        TukuiResolver,
        InstawowResolver,
        WagoResolver,
    ]
    'Default resolvers.'

    _base_catalogue_url = (
        f'https://raw.githubusercontent.com/layday/instawow-data/data/'
        f'base-catalogue-v{CATALOGUE_VERSION}.compact.json'
    )
    _catalogue_ttl = timedelta(hours=4)

    def __init__(
        self,
        config: Config,
        database: sa.Engine,
    ) -> None:
        self.config: Config = config
        self.database: sa.Engine = database

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

    @classmethod
    def from_config(cls, config: Config) -> Self:
        "Instantiate the manager from a configuration object."
        return cls(config, pkg_db.prepare_database(config.db_uri))

    @property
    def locks(self) -> LocksType:
        "Lock factory used to synchronise async operations."
        return _locks.get()

    @property
    def web_client(self) -> http.ClientSessionType:
        return _web_client.get()

    async def synchronise(self) -> ComputedCatalogue:
        "Fetch the catalogue from the interwebs and load it."
        async with self.locks[_LOAD_CATALOGUE_LOCK], self.web_client.get(
            self._base_catalogue_url,
            expire_after=self._catalogue_ttl,
            raise_for_status=True,
            trace_request_ctx=make_generic_progress_ctx('Synchronising catalogue'),
        ) as response:
            raw_catalogue = await response.read()
        return _parse_catalogue(raw_catalogue)
