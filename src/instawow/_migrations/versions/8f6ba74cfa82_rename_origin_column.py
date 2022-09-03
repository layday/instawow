"""
Rename the 'origin' column to 'source'.
"""
from functools import partial

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '8f6ba74cfa82'
down_revision = '3b37d2faccd2'
branch_labels = None
depends_on = None

batch_alter_table = partial(
    op.batch_alter_table,
    naming_convention={'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s'},
    schema=None,
)


def upgrade():
    with batch_alter_table('pkg') as batch_op:
        batch_op.alter_column('origin', new_column_name='source')

    with batch_alter_table('pkg_dep') as batch_op:
        batch_op.alter_column('pkg_origin', new_column_name='pkg_source')
        batch_op.drop_constraint('uq_id_per_foreign_key_constr', type_='unique')
        batch_op.create_unique_constraint(
            'uq_id_per_foreign_key_constr', ['id', 'pkg_source', 'pkg_id']
        )
        batch_op.drop_constraint('fk_pkg_dep_pkg_origin_pkg', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_dep_pkg_source_pkg', 'pkg', ['pkg_source', 'pkg_id'], ['source', 'id']
        )

    with batch_alter_table('pkg_folder') as batch_op:
        batch_op.alter_column('pkg_origin', new_column_name='pkg_source')
        batch_op.drop_constraint('fk_pkg_folder_pkg_origin_pkg', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_folder_pkg_source_pkg', 'pkg', ['pkg_source', 'pkg_id'], ['source', 'id']
        )

    with batch_alter_table('pkg_options') as batch_op:
        batch_op.alter_column('pkg_origin', new_column_name='pkg_source')
        batch_op.drop_constraint('fk_pkg_options_pkg_origin_pkg', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_options_pkg_source_pkg', 'pkg', ['pkg_source', 'pkg_id'], ['source', 'id']
        )


def downgrade():
    with batch_alter_table('pkg') as batch_op:
        batch_op.alter_column('source', new_column_name='origin')

    with batch_alter_table('pkg_dep') as batch_op:
        batch_op.alter_column('pkg_source', new_column_name='pkg_origin')
        batch_op.drop_constraint('uq_id_per_foreign_key_constr', type_='unique')
        batch_op.create_unique_constraint(
            'uq_id_per_foreign_key_constr', ['id', 'pkg_origin', 'pkg_id']
        )
        batch_op.drop_constraint('fk_pkg_dep_pkg_source_pkg', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_dep_pkg_origin_pkg', 'pkg', ['pkg_origin', 'pkg_id'], ['origin', 'id']
        )

    with batch_alter_table('pkg_folder') as batch_op:
        batch_op.alter_column('pkg_source', new_column_name='pkg_origin')
        batch_op.drop_constraint('fk_pkg_folder_pkg_source_pkg', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_folder_pkg_origin_pkg', 'pkg', ['pkg_origin', 'pkg_id'], ['origin', 'id']
        )

    with batch_alter_table('pkg_options') as batch_op:
        batch_op.alter_column('pkg_source', new_column_name='pkg_origin')
        batch_op.drop_constraint('fk_pkg_options_pkg_source_pkg', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_options_pkg_origin_pkg', 'pkg', ['pkg_origin', 'pkg_id'], ['origin', 'id']
        )
