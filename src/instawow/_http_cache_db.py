from __future__ import annotations

from collections.abc import Set
from contextlib import contextmanager
import os
import sqlite3
from typing import NoReturn

from aiohttp_client_cache.backends.base import BaseCache, CacheBackend, ResponseOrKey
from typing_extensions import LiteralString


@contextmanager
def acquire_cache_db_conn(db_path: os.PathLike[str]):
    db_conn = sqlite3.connect(db_path)
    db_conn.execute('PRAGMA synchronous = 0')
    yield db_conn
    db_conn.close()


class SQLiteBackend(CacheBackend):
    def __init__(self, db_conn: sqlite3.Connection, **kwargs: object):
        super().__init__(**kwargs)  # pyright: ignore
        self.responses = _SQLiteResponseCache(db_conn)
        self.redirects = _SQLiteRedirectCache(db_conn)


class _SQLiteBaseCache(BaseCache):
    TABLE: LiteralString

    def __init__(self, db_conn: sqlite3.Connection):
        super().__init__()  # pyright: ignore
        self._db_conn = db_conn
        self._db_conn.execute(
            f'CREATE TABLE IF NOT EXISTS "{self.TABLE}" (key PRIMARY KEY, value)'
        )

    async def clear(self):
        self._db_conn.execute(f'DELETE FROM "{self.TABLE}"')
        self._db_conn.execute('VACUUM')
        self._db_conn.commit()

    async def contains(self, key: str):
        cursor = self._db_conn.execute(
            f'SELECT 1 FROM "{self.TABLE}" WHERE key = ?',
            (key,),
        )
        (value,) = cursor.fetchone() or (0,)
        return value

    async def delete(self, key: str):
        self._db_conn.execute(
            f'DELETE FROM "{self.TABLE}" WHERE key = ?',
            (key,),
        )
        self._db_conn.commit()

    async def bulk_delete(self, keys: Set[str]) -> NoReturn:
        raise NotImplementedError

    async def keys(self):
        cursor = self._db_conn.execute(f'SELECT key FROM "{self.TABLE}"')
        for (value,) in cursor:
            yield value

    async def read(self, key: str):
        cursor = self._db_conn.execute(
            f'SELECT value FROM "{self.TABLE}" WHERE key = ?',
            (key,),
        )
        (value,) = cursor.fetchone() or (None,)
        return value

    async def size(self):
        cursor = self._db_conn.execute(f'SELECT COUNT(key) FROM "{self.TABLE}"')
        (value,) = cursor.fetchone()
        return value

    async def values(self):
        cursor = self._db_conn.execute(f'SELECT value FROM "{self.TABLE}"')
        for (value,) in cursor:
            yield value

    async def write(self, key: str, item: ResponseOrKey):
        self._db_conn.execute(
            f'INSERT OR REPLACE INTO "{self.TABLE}" (key, value) VALUES (?, ?)',
            (key, item),
        )
        self._db_conn.commit()


class _SQLiteRedirectCache(_SQLiteBaseCache):
    TABLE = 'redirects'


class _SQLiteResponseCache(_SQLiteBaseCache):
    TABLE = 'responses'

    async def read(self, key: str):
        return self.deserialize(await super().read(key))

    async def values(self):
        cursor = self._db_conn.execute(f'SELECT value FROM "{self.TABLE}"')
        for (value,) in cursor:
            yield self.deserialize(value)

    async def write(self, key: str, item: ResponseOrKey):
        encoded_item = self.serialize(item)
        if encoded_item:
            await super().write(key, memoryview(encoded_item))
