"""
Add UNIQUE constraint that was missing from ``pkg_dep``.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '3b37d2faccd2'
down_revision = '7204944522b1'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pkg_dep') as batch_op:
        batch_op.create_unique_constraint(
            'uq_id_per_foreign_key_constr', ['id', 'pkg_origin', 'pkg_id']
        )


def downgrade():
    with op.batch_alter_table('pkg_dep') as batch_op:
        batch_op.drop_constraint('uq_id_per_foreign_key_constr', type_='unique')
