from __future__ import annotations

import contextvars as cv
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager, AbstractContextManager, ExitStack
from functools import cached_property
from itertools import chain
from typing import TYPE_CHECKING, TypeAlias

from . import _sources, http, pkg_db
from ._utils.iteration import WeakValueDefaultDictionary
from .config import ProfileConfig
from .plugins import get_plugin_resolvers
from .resolvers import Resolvers


class _DummyLock(AbstractAsyncContextManager[None]):
    async def __aexit__(self, *args: object):
        return None


Locks: TypeAlias = Mapping[object, AbstractAsyncContextManager[None]]

locks_var = cv.ContextVar[Locks]('locks_var', default=WeakValueDefaultDictionary(_DummyLock))
web_client_var = cv.ContextVar['http.ClientSession']('web_client_var')


def _database_from_config(config: ProfileConfig):
    return pkg_db.DatabaseHandle(config.db_file)


def _resolvers_from_config(config: ProfileConfig):
    builtin_resolver_classes = list(_sources.DEFAULT_RESOLVERS)

    for resolver, access_token in (
        (r, getattr(config.global_config.access_tokens, r.requires_access_token, None))
        for r in _sources.DEFAULT_RESOLVERS
        if r.requires_access_token is not None
    ):
        if access_token is None:
            builtin_resolver_classes.remove(resolver)

    resolver_classes = chain(
        (r for g in get_plugin_resolvers() for r in g), builtin_resolver_classes
    )
    return Resolvers((r.metadata.id, r(config)) for r in resolver_classes)


class ConfigBoundCtx(AbstractContextManager['ConfigBoundCtx']):
    def __init__(self, config: ProfileConfig) -> None:
        self._exit_stack = ExitStack()

        self.config: ProfileConfig = config

    def __exit__(self, *args: object) -> None:
        self._exit_stack.close()

    @cached_property
    def database(self) -> pkg_db.DatabaseHandle:
        database = _database_from_config(self.config)
        self._exit_stack.callback(database.close)
        return database

    @cached_property
    def resolvers(self) -> Resolvers:
        return _resolvers_from_config(self.config)


if TYPE_CHECKING:
    locks: Locks
    web_client: http.ClientSession
else:

    def __getattr__(name: str):
        match name:
            case 'locks':
                return locks_var.get()
            case 'web_client':
                return web_client_var.get()
            case _:
                raise AttributeError(name)
