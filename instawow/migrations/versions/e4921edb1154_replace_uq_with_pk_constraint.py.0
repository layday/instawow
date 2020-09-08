"""
Replace the ``pkg_dep`` UNIQUE constraint with a pk.

Revision ID: e4921edb1154
Revises: 43aa3610e92a
Create Date: 2020-09-08 14:39:34.957011

"""
from contextlib import suppress

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e4921edb1154'
down_revision = '43aa3610e92a'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pkg_dep', schema=None) as batch_op:
        batch_op.drop_column('_id')
        batch_op.create_primary_key('pk_pkg_dep', ['id', 'pkg_source', 'pkg_id'])

    # ``UNIQUE`` constraint might've previously not been applied correctly
    with suppress(ValueError), op.batch_alter_table('pkg_dep', schema=None) as batch_op:
        batch_op.drop_constraint('uq_id_per_foreign_key_constr', type_='unique')


def downgrade():
    with op.batch_alter_table('pkg_dep', schema=None) as batch_op:
        batch_op.add_column(sa.Column('_id', sa.INTEGER(), nullable=False))
        batch_op.drop_constraint('pk_pkg_dep', type_='primary')
        batch_op.create_primary_key('pk_pkg_dep', ['_id'])
        batch_op.create_unique_constraint(
            'uq_id_per_foreign_key_constr', ['id', 'pkg_origin', 'pkg_id']
        )
