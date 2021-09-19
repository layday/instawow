"""
Populate the version table from installed packages.
"""
from alembic import op
from sqlalchemy import String, column, table

# revision identifiers, used by Alembic.
revision = '43aa3610e92a'
down_revision = 'd3f542de5ff4'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    pkg_version_log = table(
        'pkg_version_log',
        column('pkg_source', String),
        column('pkg_id', String),
        column('version', String),
    )
    pkgs = conn.execute('select source, id, version from pkg').fetchall()
    op.bulk_insert(
        pkg_version_log, [{'pkg_source': s, 'pkg_id': i, 'version': v} for s, i, v in pkgs]
    )


def downgrade():
    op.execute('delete from pkg_version_log')
