from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import contextvars
import os
from collections.abc import Callable, Coroutine, Set
from functools import wraps
from typing import Any, TypeVar

import diskcache
from aiohttp_client_cache import BaseCache, ResponseOrKey
from typing_extensions import ParamSpec

_U = TypeVar('_U')
_P = ParamSpec('_P')


@contextlib.contextmanager
def make_cache(cache_dir: os.PathLike[str]):
    with concurrent.futures.ThreadPoolExecutor(1, '_http_cache') as executor:
        index = diskcache.Index(os.fspath(cache_dir))
        with contextlib.closing(index.cache):
            loop = asyncio.get_running_loop()

            def run_in_thread2(fn: Callable[_P, _U]) -> Callable[_P, Coroutine[Any, Any, _U]]:
                @wraps(fn)
                async def wrapper(*args: _P.args, **kwargs: _P.kwargs):
                    run = contextvars.copy_context().run
                    return await loop.run_in_executor(executor, lambda: run(fn, *args, **kwargs))

                return wrapper

            class Cache(BaseCache):
                async def bulk_delete(self, keys: Set[str]):
                    for key in keys:
                        await self.delete(key)

                @run_in_thread2
                def clear(self):
                    return index.clear()

                @run_in_thread2
                def contains(self, key: str):
                    return key in index

                @run_in_thread2
                def delete(self, key: str):
                    try:
                        index[key]
                    except KeyError:
                        pass

                async def keys(self):
                    for key in await run_in_thread2(index.keys)():
                        yield key

                @run_in_thread2
                def read(self, key: str):
                    return index.get(key)

                @run_in_thread2
                def size(self):
                    return len(index)

                async def values(self):
                    for value in await run_in_thread2(index.values)():
                        yield value

                @run_in_thread2
                def write(self, key: str, item: ResponseOrKey):
                    index[key] = item

            yield Cache()
