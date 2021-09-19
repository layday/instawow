"""
Drop the package table's ``file_id`` column.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'f3f9957de30c'
down_revision = '8f6ba74cfa82'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pkg', schema=None) as batch_op:
        batch_op.drop_column('file_id')


def downgrade():
    with op.batch_alter_table('pkg', schema=None) as batch_op:
        batch_op.add_column(sa.Column('file_id', sa.VARCHAR(), nullable=False))
