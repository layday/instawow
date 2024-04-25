from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

_U = TypeVar('_U')
_P = ParamSpec('_P')


async def gather(it: Iterable[Awaitable[_U]]) -> list[_U]:
    return await asyncio.gather(*it)


def run_in_thread(fn: Callable[_P, _U]) -> Callable[_P, Awaitable[_U]]:
    @wraps(fn)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs):
        return asyncio.to_thread(fn, *args, **kwargs)

    return wrapper


async def cancel_tasks(tasks: Iterable[asyncio.Task[Any]]) -> None:
    incomplete_tasks = [t for t in tasks if not t.done()]
    for task in incomplete_tasks:
        task.cancel()
    await asyncio.gather(*incomplete_tasks, return_exceptions=True)
