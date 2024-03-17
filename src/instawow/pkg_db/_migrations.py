from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

import sqlalchemy as sa


class Migration(Protocol):
    def upgrade(self, connection: sa.Connection) -> None: ...

    def downgrade(self, connection: sa.Connection) -> None: ...


class BaseMigration(Migration):
    def _with_table_op(self, connection: sa.Connection) -> None: ...


MIGRATIONS: Mapping[int, Migration] = {}
