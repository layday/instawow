"""
Create the ``pkg_version_log`` table to track previously-installed package versions.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd3f542de5ff4'
down_revision = 'f3f9957de30c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pkg_version_log',
        sa.Column('version', sa.String(), nullable=False),
        sa.Column('install_time', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('pkg_source', sa.String(), nullable=False),
        sa.Column('pkg_id', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('version', 'pkg_source', 'pkg_id'),
    )


def downgrade():
    op.drop_table('pkg_version_log')
