from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import contextvars
import os
from collections.abc import Callable, Coroutine, Set
from functools import wraps
from typing import Any, TypeVar, cast

import aiohttp_client_cache
import diskcache
from typing_extensions import ParamSpec

_U = TypeVar('_U')
_P = ParamSpec('_P')


@contextlib.asynccontextmanager
async def make_cache(cache_dir: os.PathLike[str]):
    with concurrent.futures.ThreadPoolExecutor(1, '_http_cache') as executor:
        loop = asyncio.get_running_loop()

        def run_in_thread2(fn: Callable[_P, _U]) -> Callable[_P, Coroutine[Any, Any, _U]]:
            @wraps(fn)
            async def wrapper(*args: _P.args, **kwargs: _P.kwargs):
                return await loop.run_in_executor(
                    executor, lambda: contextvars.copy_context().run(fn, *args, **kwargs)
                )

            return wrapper

        # diskcache will only close the sqlite connection if it was initialised
        # in the same thread.
        cache = await run_in_thread2(diskcache.Cache)(os.fspath(cache_dir))

        class Cache(aiohttp_client_cache.BaseCache):
            @run_in_thread2
            def bulk_delete(self, keys: Set[str]):
                for key in keys:
                    cache.delete(key)

            @run_in_thread2
            def clear(self):
                cache.clear()

            @run_in_thread2
            def contains(self, key: str):
                return key in cache

            @run_in_thread2
            def delete(self, key: str):
                cache.delete(key)

            async def keys(self):
                with contextlib.suppress(StopIteration):
                    iter_keys = iter(cache)

                    while True:
                        yield (await run_in_thread2(next)(iter_keys))

            @run_in_thread2
            def read(self, key: str):
                return cache.get(key)

            @run_in_thread2
            def size(self):
                return len(cache)

            async def values(self):
                async for key in self.keys():
                    yield cast(aiohttp_client_cache.ResponseOrKey, run_in_thread2(cache.get)(key))

            @run_in_thread2
            def write(self, key: str, item: aiohttp_client_cache.ResponseOrKey):
                cache[key] = item

        try:
            yield Cache()
        finally:
            await run_in_thread2(cache.close)()
