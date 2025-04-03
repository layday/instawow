from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import ExitStack, closing, contextmanager

type Connection = sqlite3.Connection
type Row = sqlite3.Row


_VERSION = 1

_SCHEMA = f"""
CREATE TABLE pkg (
    source VARCHAR NOT NULL,
    id VARCHAR NOT NULL,
    slug VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    url VARCHAR NOT NULL,
    download_url VARCHAR NOT NULL,
    date_published DATETIME NOT NULL,
    version VARCHAR NOT NULL,
    changelog_url VARCHAR NOT NULL,
    PRIMARY KEY (source, id)
);

CREATE TABLE pkg_version_log (
    version VARCHAR NOT NULL,
    install_time DATETIME DEFAULT (CURRENT_TIMESTAMP) NOT NULL,
    pkg_source VARCHAR NOT NULL,
    pkg_id VARCHAR NOT NULL,
    PRIMARY KEY (version, pkg_source, pkg_id)
);
CREATE INDEX pkg_version_log_faux_fk ON pkg_version_log (pkg_source, pkg_id);

CREATE TABLE pkg_options (
    any_flavour BOOLEAN NOT NULL,
    any_release_type BOOLEAN NOT NULL,
    version_eq BOOLEAN NOT NULL,
    pkg_source VARCHAR NOT NULL,
    pkg_id VARCHAR NOT NULL,
    PRIMARY KEY (pkg_source, pkg_id),
    CONSTRAINT fk_pkg_options_pkg_source_and_id
        FOREIGN KEY (pkg_source, pkg_id)
        REFERENCES pkg (source, id)
        ON DELETE CASCADE
);
CREATE UNIQUE INDEX pkg_options_fk ON pkg_options (pkg_source, pkg_id);

CREATE TABLE pkg_folder (
    name VARCHAR NOT NULL,
    pkg_source VARCHAR NOT NULL,
    pkg_id VARCHAR NOT NULL,
    PRIMARY KEY (name),
    CONSTRAINT fk_pkg_folder_pkg_source_and_id
        FOREIGN KEY (pkg_source, pkg_id)
        REFERENCES pkg (source, id)
        ON DELETE CASCADE
);
CREATE INDEX pkg_folder_fk ON pkg_folder (pkg_source, pkg_id);

CREATE TABLE pkg_dep (
    id VARCHAR NOT NULL,
    pkg_source VARCHAR NOT NULL,
    pkg_id VARCHAR NOT NULL,
    PRIMARY KEY (id, pkg_source, pkg_id),
    CONSTRAINT fk_pkg_dep_pkg_source_and_id
        FOREIGN KEY (pkg_source, pkg_id)
        REFERENCES pkg (source, id)
        ON DELETE CASCADE
);
CREATE INDEX pkg_dep_fk ON pkg_dep (pkg_source, pkg_id);

PRAGMA user_version = {_VERSION};
"""


def _get_version(connection: Connection) -> int | None:
    has_pkg_table = connection.execute('PRAGMA table_info("pkg")').fetchone()
    if has_pkg_table:
        (user_version,) = connection.execute('PRAGMA user_version').fetchone()
        return user_version


def _create(connection: Connection):
    with connection as transaction:
        transaction.executescript(_SCHEMA)


def _migrate(connection: Connection, current_version: int, new_version: int):
    from ._migrations import MIGRATIONS

    # SQLite migration reference:
    # https://www.sqlite.org/lang_altertable.html#otheralter

    with (
        connection as transaction,  # Steps 2 and 11.
        ExitStack() as exit_stack,
    ):
        # Steps 1 and 12.
        transaction.execute('PRAGMA foreign_keys = OFF')
        exit_stack.callback(lambda: transaction.execute('PRAGMA foreign_keys = ON'))

        if new_version > current_version:
            for intermediate_version in range(current_version + 1, new_version + 1):
                MIGRATIONS[intermediate_version]().upgrade(transaction)

        else:
            for intermediate_version in range(current_version, new_version, -1):
                MIGRATIONS[intermediate_version]().downgrade(transaction)

        # Step 10.
        transaction.execute('PRAGMA foreign_key_check')

        # Stamp database with new version.
        transaction.execute(f'PRAGMA user_version = {new_version}')


def _configure(connection: Connection):
    connection.execute('PRAGMA foreign_keys = ON')
    connection.execute('PRAGMA journal_mode = WAL')
    connection.execute('PRAGMA synchronous = NORMAL')
    # connection.set_trace_callback(print)


def prepare_database(path: os.PathLike[str]) -> Connection:
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    _configure(connection)

    current_version = _get_version(connection)
    if current_version is not None and current_version != _VERSION:
        _migrate(connection, current_version, _VERSION)
    elif current_version is None:
        _create(connection)

    return connection


@contextmanager
def transact(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    with connection:
        yield connection


@contextmanager
def use_tuple_factory(connection: sqlite3.Connection) -> Iterator[sqlite3.Cursor]:
    with closing(connection.cursor()) as cursor:
        cursor.row_factory = None
        yield cursor
