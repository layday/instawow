"""
Change the `pkg_options` table's `strategy` column to be
one of 'default', 'latest'.
"""
from functools import partial, update_wrapper

from alembic import op
from sqlalchemy import Enum, String
from sqlalchemy.sql import column, table

# revision identifiers, used by Alembic.
revision = 'e4ae835a34be'
down_revision = None
branch_labels = None
depends_on = None


def _migrate(new_type: Enum, old_val: str, new_val: str) -> None:
    intermediate_type = String
    pkg_options = table('pkg_options', column('strategy', intermediate_type))

    with op.batch_alter_table('pkg_options') as batch_op:
        batch_op.alter_column('strategy', type_=intermediate_type)

    op.execute(
        pkg_options.update()
        .where(pkg_options.c.strategy == op.inline_literal(old_val))
        .values({'strategy': op.inline_literal(new_val)})
    )

    with op.batch_alter_table('pkg_options') as batch_op:
        batch_op.alter_column('strategy', type_=new_type)


upgrade = update_wrapper(
    partial(_migrate, Enum('default', 'latest'), 'canonical', 'default'), _migrate
)
downgrade = update_wrapper(
    partial(_migrate, Enum('canonical', 'latest'), 'default', 'canonical'), _migrate
)
