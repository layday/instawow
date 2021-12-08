from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKeyConstraint,
    MetaData,
    String,
    Table,
    TypeDecorator,
    func,
    text,
)
from sqlalchemy.exc import OperationalError
from sqlalchemy.future import Engine


class TZDateTime(TypeDecorator[datetime]):
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
    Column('date_published', TZDateTime, nullable=False),
    Column('version', String, nullable=False),
    Column('changelog_url', String, nullable=False),
)

pkg_options = Table(
    'pkg_options',
    metadata,
    Column('strategy', String, nullable=False),
    Column('pkg_source', String, primary_key=True),
    Column('pkg_id', String, primary_key=True),
    ForeignKeyConstraint(
        ['pkg_source', 'pkg_id'],
        ['pkg.source', 'pkg.id'],
        name='fk_pkg_options_pkg_source_and_id',
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
    ),
)

pkg_version_log = Table(
    'pkg_version_log',
    metadata,
    Column('version', String, primary_key=True),
    Column('install_time', TZDateTime, nullable=False, server_default=func.now()),
    Column('pkg_source', String, primary_key=True),
    Column('pkg_id', String, primary_key=True),
    ForeignKeyConstraint(
        ['pkg_source', 'pkg_id'],
        ['pkg.source', 'pkg.id'],
        name='fk_pkg_version_log_pkg_source_and_id',
    ),
)


class DatabaseState(IntEnum):
    current = 0
    old = 1
    uninitialised = 2


def get_database_state(engine: Engine, revision: str) -> DatabaseState:
    with engine.connect() as connection:
        try:
            state = connection.execute(
                text(
                    'SELECT ifnull((SELECT 0 FROM alembic_version WHERE version_num == :revision), 1)',
                ),
                {'revision': revision},
            ).scalar()
        except OperationalError:
            state = connection.execute(
                text(
                    'SELECT ifnull((SELECT 1 FROM sqlite_master WHERE type = "table" LIMIT 1), 2)',
                )
            ).scalar()

    return DatabaseState(state)


def migrate_database(engine: Engine, revision: str) -> None:
    database_state = get_database_state(engine, revision)
    if database_state != DatabaseState.current:
        import alembic.command
        import alembic.config

        alembic_config = alembic.config.Config()
        alembic_config.set_main_option('script_location', f'{__package__}:migrations')
        alembic_config.set_main_option('sqlalchemy.url', str(engine.url))

        if database_state == DatabaseState.uninitialised:
            metadata.create_all(engine)
            alembic.command.stamp(alembic_config, revision)
        else:
            alembic.command.upgrade(alembic_config, revision)
