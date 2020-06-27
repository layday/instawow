"""
Make basenames out of add-on paths.
"""
from pathlib import Path

from alembic import context, op
from sqlalchemy import String, column, table

# revision identifiers, used by Alembic.
revision = '58a8306c3a5b'
down_revision = 'e4ae835a34be'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pkg_folder') as batch_op:
        batch_op.alter_column('path', new_column_name='name')

    pkg_folder = table('pkg_folder', column('name', String))
    conn = op.get_bind()
    for (folder,) in conn.execute(pkg_folder.select()):
        conn.execute(
            pkg_folder.update()
            .where(pkg_folder.c.name == op.inline_literal(folder))
            .values({'name': Path(folder).name})
        )


def downgrade():
    addon_dir = Path(context.get_x_argument(as_dictionary=True).get('addon_dir'))

    with op.batch_alter_table('pkg_folder') as batch_op:
        batch_op.alter_column('name', new_column_name='path')

    pkg_folder = table('pkg_folder', column('path', String))
    conn = op.get_bind()
    for (folder,) in conn.execute(pkg_folder.select()):
        conn.execute(
            pkg_folder.update()
            .where(pkg_folder.c.path == op.inline_literal(folder))
            .values({'path': str(addon_dir / folder)})
        )
