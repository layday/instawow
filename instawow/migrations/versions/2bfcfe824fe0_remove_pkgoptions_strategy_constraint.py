"""
Remove ``PkgOptions`` strategy constraint.
"""
from alembic import op
from sqlalchemy import Enum, String

# revision identifiers, used by Alembic.
revision = '2bfcfe824fe0'
down_revision = '58a8306c3a5b'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pkg_options') as batch_op:
        batch_op.alter_column('strategy', type_=String)


def downgrade():
    with op.batch_alter_table('pkg_options') as batch_op:
        batch_op.alter_column('strategy', type_=Enum('default', 'latest'))
