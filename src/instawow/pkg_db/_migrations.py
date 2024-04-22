from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import Protocol

from . import Connection


class Migration(Protocol):
    def upgrade(self, connection: Connection) -> None: ...

    def downgrade(self, connection: Connection) -> None: ...


class _BaseMigration(Migration, Protocol):
    @contextlib.contextmanager
    def _with_table_op(self, connection: Connection):
        yield


class _Migration_1(_BaseMigration):
    def upgrade(self, connection: Connection) -> None:
        connection.execute(
            'CREATE UNIQUE INDEX pkg_options_fk ON pkg_options (pkg_source, pkg_id)',
        )
        connection.execute(
            'CREATE INDEX pkg_folder_fk ON pkg_folder (pkg_source, pkg_id)',
        )
        connection.execute(
            'CREATE INDEX pkg_dep_fk ON pkg_dep (pkg_source, pkg_id)',
        )
        connection.execute(
            'CREATE INDEX pkg_version_log_faux_fk ON pkg_version_log (pkg_source, pkg_id)',
        )

    def downgrade(self, connection: Connection) -> None:
        connection.execute(
            'DROP INDEX pkg_options_fk',
        )
        connection.execute(
            'DROP INDEX pkg_folder_fk',
        )
        connection.execute(
            'DROP INDEX pkg_dep_fk',
        )
        connection.execute(
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
