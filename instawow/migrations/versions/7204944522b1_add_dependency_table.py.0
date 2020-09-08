"""
Add dependency table.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '7204944522b1'
down_revision = '2bfcfe824fe0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'pkg_dep',
        sa.Column('_id', sa.Integer(), nullable=False),
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('pkg_origin', sa.String(), nullable=False),
        sa.Column('pkg_id', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ['pkg_origin', 'pkg_id'],
            ['pkg.origin', 'pkg.id'],
        ),
        sa.PrimaryKeyConstraint('_id'),
    )


def downgrade():
    op.drop_table('pkg_dep')
