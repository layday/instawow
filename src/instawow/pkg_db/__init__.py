from __future__ import annotations

import contextlib
import sqlite3
from datetime import datetime, timezone

import sqlalchemy
import sqlalchemy.event
import sqlalchemy.exc

sa = sqlalchemy


_VERSION = 0


class _TZDateTime(sa.TypeDecorator[datetime]):
    impl = sa.DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None:
            if not value.tzinfo:
                raise TypeError('tzinfo is required')
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value: datetime | None, dialect: object) -> datetime | None:
        if value is not None:
            value = value.replace(tzinfo=timezone.utc)
        return value

    @property
    def python_type(self) -> type[datetime]:
        return datetime


_metadata = sa.MetaData()


pkg = sa.Table(
    'pkg',
    _metadata,
    sa.Column('source', sa.String, primary_key=True),
    sa.Column('id', sa.String, primary_key=True),
    sa.Column('slug', sa.String, nullable=False),
    sa.Column('name', sa.String, nullable=False),
    sa.Column('description', sa.String, nullable=False),
    sa.Column('url', sa.String, nullable=False),
    sa.Column('download_url', sa.String, nullable=False),
    sa.Column('date_published', _TZDateTime, nullable=False),
    sa.Column('version', sa.String, nullable=False),
    sa.Column('changelog_url', sa.String, nullable=False),
)

pkg_options = sa.Table(
    'pkg_options',
    _metadata,
    sa.Column('any_flavour', sa.Boolean, nullable=False),
    sa.Column('any_release_type', sa.Boolean, nullable=False),
    sa.Column('version_eq', sa.Boolean, nullable=False),
    sa.Column('pkg_source', sa.String, primary_key=True),
    sa.Column('pkg_id', sa.String, primary_key=True),
    sa.ForeignKeyConstraint(
        ['pkg_source', 'pkg_id'],
        ['pkg.source', 'pkg.id'],
        name='fk_pkg_options_pkg_source_and_id',
        ondelete='CASCADE',
    ),
)

pkg_folder = sa.Table(
    'pkg_folder',
    _metadata,
    sa.Column('name', sa.String, primary_key=True),
    sa.Column('pkg_source', sa.String, nullable=False),
    sa.Column('pkg_id', sa.String, nullable=False),
    sa.ForeignKeyConstraint(
        ['pkg_source', 'pkg_id'],
        ['pkg.source', 'pkg.id'],
        name='fk_pkg_folder_pkg_source_and_id',
        ondelete='CASCADE',
    ),
)

pkg_dep = sa.Table(
    'pkg_dep',
    _metadata,
    sa.Column('id', sa.String, primary_key=True),
    sa.Column('pkg_source', sa.String, primary_key=True),
    sa.Column('pkg_id', sa.String, primary_key=True),
    sa.ForeignKeyConstraint(
        ['pkg_source', 'pkg_id'],
        ['pkg.source', 'pkg.id'],
        name='fk_pkg_dep_pkg_source_and_id',
        ondelete='CASCADE',
    ),
)

pkg_version_log = sa.Table(
    'pkg_version_log',
    _metadata,
    sa.Column('version', sa.String, primary_key=True),
    sa.Column('install_time', _TZDateTime, nullable=False, server_default=sa.func.now()),
    sa.Column('pkg_source', sa.String, primary_key=True),
    sa.Column('pkg_id', sa.String, primary_key=True),
)


def _get_version(engine: sa.Engine) -> int:
    with engine.connect() as connection:
        return connection.execute(sa.text('PRAGMA user_version')).scalar_one()


def _migrate(engine: sa.Engine, current_version: int, new_version: int) -> None:
    from ._migrations import MIGRATIONS

    # SQLite migration reference:
    # https://www.sqlite.org/lang_altertable.html#otheralter

    with (
        engine.begin() as transaction,  # Steps 2 and 11.
        contextlib.ExitStack() as exit_stack,
    ):
        # Steps 1 and 12.
        transaction.exec_driver_sql('PRAGMA foreign_keys = OFF')
        exit_stack.callback(lambda: transaction.exec_driver_sql('PRAGMA foreign_keys = ON'))

        for intermediate_version in range(current_version + 1, new_version + 1):
            MIGRATIONS[intermediate_version].upgrade(transaction)

        # Step 10.
        transaction.exec_driver_sql('PRAGMA foreign_key_check')

        # Stamp database with new version.
        transaction.exec_driver_sql(f'PRAGMA user_version = {new_version}')


def _set_fk_pragma(dbapi_connection: sqlite3.Connection, connection_record: object):
    with contextlib.closing(dbapi_connection.cursor()) as cursor:
        cursor.execute('PRAGMA foreign_keys = ON')


def prepare_database(uri: str) -> sa.Engine:
    "Connect to and optionally create or migrate the database."
    engine = sa.create_engine(
        uri,
        # echo=True,
    )
    sa.event.listen(engine, 'connect', _set_fk_pragma)

    current_version = _get_version(engine)
    if current_version != _VERSION:
        _migrate(engine, current_version, _VERSION)
    else:
        _metadata.create_all(engine)

    return engine
