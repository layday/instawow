"""
Add the package changelog column.

Revision ID: 764fa963cc71
Revises: e4921edb1154
Create Date: 2021-03-20 02:46:24.528320

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '764fa963cc71'
down_revision = 'e4921edb1154'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pkg', schema=None) as batch_op:
        batch_op.add_column(sa.Column('changelog_url', sa.String(), nullable=True))

    conn = op.get_bind()
    conn.execute('update pkg set changelog_url = "data:,"')

    with op.batch_alter_table('pkg', schema=None) as batch_op:
        batch_op.alter_column('changelog_url', nullable=False)


def downgrade():
    with op.batch_alter_table('pkg', schema=None) as batch_op:
        batch_op.drop_column('changelog_url')
