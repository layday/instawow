from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from functools import partial, update_wrapper
from typing import Any, ParamSpec, TypeVar

_U = TypeVar('_U')
_P = ParamSpec('_P')


async def gather(it: Iterable[Awaitable[_U]]) -> list[_U]:
    return await asyncio.gather(*it)


def run_in_thread(fn: Callable[_P, _U]) -> Callable[_P, Awaitable[_U]]:
    return update_wrapper(partial(asyncio.to_thread, fn), fn)


async def cancel_tasks(tasks: Iterable[asyncio.Task[Any]]) -> None:
    incomplete_tasks = [t for t in tasks if not t.done()]
    for task in incomplete_tasks:
        task.cancel()
    await asyncio.gather(*incomplete_tasks, return_exceptions=True)
