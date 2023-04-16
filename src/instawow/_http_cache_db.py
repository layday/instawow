from __future__ import annotations

import os
import sqlite3
from collections.abc import Set
from contextlib import contextmanager
from typing import NoReturn

from aiohttp_client_cache import BaseCache, CacheBackend, ResponseOrKey
from typing_extensions import LiteralString


@contextmanager
def acquire_cache_connection(parent_folder_path: os.PathLike[str]):
    with sqlite3.connect(os.path.join(parent_folder_path, '_aiohttp-cache.sqlite')) as connection:
        connection.execute('PRAGMA journal_mode = wal')
        connection.execute('PRAGMA synchronous = normal')
        yield connection


class SQLiteBackend(CacheBackend):
    def __init__(self, connection: sqlite3.Connection, **kwargs: object):
        super().__init__(**kwargs)  # pyright: ignore[reportUnknownMemberType]
        self.responses = _SQLitePickleCache().attach('responses', connection)
        self.redirects = _SQLiteSimpleCache().attach('redirects', connection)


class _SQLiteSimpleCache(BaseCache):
    def attach(self, table_name: LiteralString, connection: sqlite3.Connection):
        self.table_name = table_name
        self._connection = connection
        self._connection.execute(
            f'CREATE TABLE IF NOT EXISTS "{self.table_name}" (key PRIMARY KEY, value)'
        )
        return self

    async def clear(self) -> NoReturn:
        raise NotImplementedError

    async def contains(self, key: str):
        cursor = self._connection.execute(
            f'SELECT 1 FROM "{self.table_name}" WHERE key = ?',
            (key,),
        )
        (value,) = cursor.fetchone() or (0,)
        return value

    async def delete(self, key: str):
        self._connection.execute(
            f'DELETE FROM "{self.table_name}" WHERE key = ?',
            (key,),
        )
        self._connection.commit()

    async def bulk_delete(self, keys: Set[str]) -> NoReturn:
        raise NotImplementedError

    async def keys(self):
        cursor = self._connection.execute(f'SELECT key FROM "{self.table_name}"')
        for (value,) in cursor:
            yield value

    async def read(self, key: str):
        cursor = self._connection.execute(
            f'SELECT value FROM "{self.table_name}" WHERE key = ?',
            (key,),
        )
        (value,) = cursor.fetchone() or (None,)
        return value

    async def size(self):
        cursor = self._connection.execute(f'SELECT COUNT(key) FROM "{self.table_name}"')
        (value,) = cursor.fetchone()
        return value

    async def values(self):
        cursor = self._connection.execute(f'SELECT value FROM "{self.table_name}"')
        for (value,) in cursor:
            yield value

    async def write(self, key: str, item: ResponseOrKey):
        self._connection.execute(
            f'INSERT OR REPLACE INTO "{self.table_name}" (key, value) VALUES (?, ?)',
            (key, item),
        )
        self._connection.commit()


class _SQLitePickleCache(_SQLiteSimpleCache):
    async def read(self, key: str):
        return self.deserialize(await super().read(key))

    async def values(self):
        cursor = self._connection.execute(f'SELECT value FROM "{self.table_name}"')
        for (value,) in cursor:
            yield self.deserialize(value)

    async def write(self, key: str, item: ResponseOrKey):
        encoded_item = self.serialize(item)
        if encoded_item:
            await super().write(key, memoryview(encoded_item))
