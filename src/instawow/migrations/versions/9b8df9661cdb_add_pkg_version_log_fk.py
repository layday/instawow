"""
Create foreign key constraint on ``pkg_version_log``.

Revision ID: 9b8df9661cdb
Revises: 764fa963cc71
Create Date: 2021-09-25 18:29:27.577648

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '9b8df9661cdb'
down_revision = '764fa963cc71'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pkg_version_log', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_pkg_version_log_pkg_source_and_id',
            'pkg',
            ['pkg_source', 'pkg_id'],
            ['source', 'id'],
        )


def downgrade():
    with op.batch_alter_table('pkg_version_log', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pkg_version_log_pkg_source_and_id', type_='foreignkey')
