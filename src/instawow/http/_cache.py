from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import os
from collections.abc import Callable, Set
from functools import partial
from typing import Never

import aiohttp_client_cache
import diskcache

_http_cache_name = '_http_v1'


@contextlib.asynccontextmanager
async def make_cache(parent_dir: os.PathLike[str]):
    with concurrent.futures.ThreadPoolExecutor(1, '_http_cache') as executor:
        loop = asyncio.get_running_loop()

        def run_in_thread2[**P, T](fn: Callable[P, T]):
            async def wrapper(*args: P.args, **kwargs: P.kwargs):
                return await loop.run_in_executor(executor, partial(fn, *args, **kwargs))

            return wrapper

        # diskcache will only close the sqlite connection if it was initialised
        # in the same thread.
        cache = await run_in_thread2(diskcache.Cache)(os.path.join(parent_dir, _http_cache_name))

        def make_cache_wrapper(prefix: str):
            class Cache(aiohttp_client_cache.BaseCache):
                @run_in_thread2
                def bulk_delete(self, keys: Set[str]):
                    for key in keys:
                        cache.delete((prefix, key))

                @run_in_thread2
                def contains(self, key: str):
                    return (prefix, key) in cache

                @run_in_thread2
                def delete(self, key: str):
                    cache.delete((prefix, key))

                @run_in_thread2
                def read(self, key: str):
                    return cache.get((prefix, key))

                @run_in_thread2
                def write(self, key: str, item: aiohttp_client_cache.ResponseOrKey):
                    cache[prefix, key] = item

                async def clear(self) -> Never:
                    raise NotImplementedError

                async def keys(self):
                    if False:  # pragma: no cover
                        yield
                    raise NotImplementedError

                async def values(self):
                    if False:  # pragma: no cover
                        yield
                    raise NotImplementedError

                async def size(self) -> Never:
                    raise NotImplementedError

            return Cache()

        try:
            yield make_cache_wrapper('responses'), make_cache_wrapper('redirects')
        finally:
            await run_in_thread2(cache.close)()
