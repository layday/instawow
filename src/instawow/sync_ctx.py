from __future__ import annotations

import contextvars as cv
from collections.abc import Mapping
from contextlib import AbstractAsyncContextManager

type Locks = Mapping[object, AbstractAsyncContextManager[None]]


@object.__new__
class _DummyLock(AbstractAsyncContextManager[None]):
    async def __aexit__(self, *args: object):
        pass


class _dummy_lock_dict(dict[object, _DummyLock]):
    def __missing__(self, key: object):
        return _DummyLock


_locks_var = cv.ContextVar[Locks]('_locks_var', default=_dummy_lock_dict())  # noqa: B039


@object.__new__
class locks:
    def __call__(self) -> Locks:
        return _locks_var.get()

    set = staticmethod(_locks_var.set)
    reset = staticmethod(_locks_var.reset)
