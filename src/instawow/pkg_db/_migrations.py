from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import Protocol

import sqlalchemy as sa


class Migration(Protocol):
    def upgrade(self, connection: sa.Connection) -> None: ...

    def downgrade(self, connection: sa.Connection) -> None: ...


class _BaseMigration(Migration, Protocol):
    @contextlib.contextmanager
    def _with_table_op(self, connection: sa.Connection):
        yield


class _Migration_1(_BaseMigration):
    def upgrade(self, connection: sa.Connection) -> None:
        connection.exec_driver_sql(
            'CREATE UNIQUE INDEX pkg_options_fk ON pkg_options (pkg_source, pkg_id)',
        )
        connection.exec_driver_sql(
            'CREATE INDEX pkg_folder_fk ON pkg_folder (pkg_source, pkg_id)',
        )
        connection.exec_driver_sql(
            'CREATE INDEX pkg_dep_fk ON pkg_dep (pkg_source, pkg_id)',
        )
        connection.exec_driver_sql(
            'CREATE INDEX pkg_version_log_faux_fk ON pkg_version_log (pkg_source, pkg_id)',
        )

    def downgrade(self, connection: sa.Connection) -> None:
        connection.exec_driver_sql(
            'DROP INDEX pkg_options_fk',
        )
        connection.exec_driver_sql(
            'DROP INDEX pkg_folder_fk',
        )
        connection.exec_driver_sql(
            'DROP INDEX pkg_dep_fk',
        )
        connection.exec_driver_sql(
            'DROP INDEX pkg_version_log_faux_fk',
        )


MIGRATIONS: Mapping[int, type[Migration]] = dict(
    enumerate(
        [
            _Migration_1,
        ],
        start=1,
    )
)
