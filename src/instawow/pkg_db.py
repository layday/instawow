from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from enum import IntEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Engine,
    ForeignKeyConstraint,
    MetaData,
    String,
    Table,
    TypeDecorator,
    create_engine,
    func,
    text,
)
from sqlalchemy.event import listen
from sqlalchemy.exc import OperationalError

DB_REVISION = '98716a7301f8'


class _TZDateTime(TypeDecorator[datetime]):
    impl = DateTime
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


metadata = MetaData()


pkg = Table(
    'pkg',
    metadata,
    Column('source', String, primary_key=True),
    Column('id', String, primary_key=True),
    Column('slug', String, nullable=False),
    Column('name', String, nullable=False),
    Column('description', String, nullable=False),
    Column('url', String, nullable=False),
    Column('download_url', String, nullable=False),
    Column('date_published', _TZDateTime, nullable=False),
    Column('version', String, nullable=False),
    Column('changelog_url', String, nullable=False),
)

pkg_options = Table(
    'pkg_options',
    metadata,
    Column('any_flavour', Boolean, nullable=False),
    Column('any_release_type', Boolean, nullable=False),
    Column('version_eq', Boolean, nullable=False),
    Column('pkg_source', String, primary_key=True),
    Column('pkg_id', String, primary_key=True),
    ForeignKeyConstraint(
        ['pkg_source', 'pkg_id'],
        ['pkg.source', 'pkg.id'],
        name='fk_pkg_options_pkg_source_and_id',
        ondelete='CASCADE',
    ),
)

pkg_folder = Table(
    'pkg_folder',
    metadata,
    Column('name', String, primary_key=True),
    Column('pkg_source', String, nullable=False),
    Column('pkg_id', String, nullable=False),
    ForeignKeyConstraint(
        ['pkg_source', 'pkg_id'],
        ['pkg.source', 'pkg.id'],
        name='fk_pkg_folder_pkg_source_and_id',
        ondelete='CASCADE',
    ),
)

pkg_dep = Table(
    'pkg_dep',
    metadata,
    Column('id', String, primary_key=True),
    Column('pkg_source', String, primary_key=True),
    Column('pkg_id', String, primary_key=True),
    ForeignKeyConstraint(
        ['pkg_source', 'pkg_id'],
        ['pkg.source', 'pkg.id'],
        name='fk_pkg_dep_pkg_source_and_id',
        ondelete='CASCADE',
    ),
)

pkg_version_log = Table(
    'pkg_version_log',
    metadata,
    Column('version', String, primary_key=True),
    Column('install_time', _TZDateTime, nullable=False, server_default=func.now()),
    Column('pkg_source', String, primary_key=True),
    Column('pkg_id', String, primary_key=True),
)


class _DatabaseState(IntEnum):
    Current = 0
    Old = 1
    Uninitialised = 2


def _get_database_state(engine: Engine, revision: str) -> _DatabaseState:
    with engine.connect() as connection:
        try:
            (state,) = connection.execute(
                text(
                    'SELECT ifnull((SELECT 0 FROM alembic_version WHERE version_num == :revision), 1)',
                ),
                {'revision': revision},
            ).one()
        except OperationalError:
            (state,) = connection.execute(
                text(
                    'SELECT ifnull((SELECT 1 FROM sqlite_master WHERE type = "table" LIMIT 1), 2)',
                )
            ).one()

    return _DatabaseState(state)


def _set_sqlite_pragma(dbapi_connection: sqlite3.Connection, connection_record: object):
    dbapi_connection.execute('PRAGMA foreign_keys = ON')


def prepare_database(uri: str) -> Engine:
    "Connect to and optionally create or migrate the database from a configuration object."
    engine = create_engine(
        uri,
        # echo=True,
    )
    listen(engine, 'connect', _set_sqlite_pragma)

    database_state = _get_database_state(engine, DB_REVISION)
    if database_state is not _DatabaseState.Current:
        import alembic.command
        import alembic.config

        alembic_config = alembic.config.Config()
        alembic_config.set_main_option('script_location', f'{__spec__.parent}:_migrations')
        alembic_config.set_main_option('sqlalchemy.url', str(engine.url))

        if database_state is _DatabaseState.Uninitialised:
            metadata.create_all(engine)
            alembic.command.stamp(alembic_config, DB_REVISION)
        else:
            alembic.command.upgrade(alembic_config, DB_REVISION)

    return engine
