# pyright: basic

from __future__ import annotations

import os
from collections.abc import Set

import diskcache
from aiohttp_client_cache import BaseCache, ResponseOrKey


def make_disk_cache(cache_dir: os.PathLike[str]):
    return _DiskCacheCache(
        diskcache.Index(os.fspath(cache_dir)),
    )


class _DiskCacheCache(BaseCache):
    def __init__(self, cache: diskcache.Index, **kwargs):
        super().__init__(**kwargs)
        self.__cache = cache

    async def bulk_delete(self, keys: Set[str]):
        for key in keys:
            await self.delete(key)

    async def clear(self):
        return self.__cache.clear()

    async def contains(self, key: str):
        return key in self.__cache

    async def delete(self, key: str):
        try:
            self.__cache[key]
        except KeyError:
            pass

    async def keys(self):
        for key in self.__cache.keys():
            yield key

    async def read(self, key: str):
        return self.__cache.get(key)

    async def size(self):
        return len(self.__cache)

    async def values(self):
        for value in self.__cache.values():
            yield value

    async def write(self, key: str, item: ResponseOrKey):
        self.__cache[key] = item
