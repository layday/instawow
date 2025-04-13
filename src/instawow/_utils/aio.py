from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Collection, Iterable
from functools import partial, update_wrapper


async def gather[T](it: Iterable[Awaitable[T]]) -> list[T]:
    return await asyncio.gather(*it)


def run_in_thread[**P, T](fn: Callable[P, T]) -> Callable[P, Awaitable[T]]:
    return update_wrapper(partial(asyncio.to_thread, fn), fn)


async def cancel_tasks(tasks: Collection[asyncio.Task[object]]) -> None:
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
