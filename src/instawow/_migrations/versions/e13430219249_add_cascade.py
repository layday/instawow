"""
Add cascade deletes to the pkg table's dependents.

Revision ID: e13430219249
Revises: 75f69831f74f
Create Date: 2022-04-30 22:29:49.359123

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'e13430219249'
down_revision = '75f69831f74f'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table(
        'pkg_dep',
        schema=None,
        reflect_args=[
            sa.ForeignKeyConstraint(
                ['pkg_source', 'pkg_id'],
                ['pkg.source', 'pkg.id'],
                name='fk_pkg_dep_pkg_source_and_id',
            ),
        ],
    ) as batch_op:
        batch_op.drop_constraint('fk_pkg_dep_pkg_source_and_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_dep_pkg_source_and_id',
            'pkg',
            ['pkg_source', 'pkg_id'],
            ['source', 'id'],
            ondelete='CASCADE',
        )

    with op.batch_alter_table(
        'pkg_folder',
        schema=None,
        reflect_args=[
            sa.ForeignKeyConstraint(
                ['pkg_source', 'pkg_id'],
                ['pkg.source', 'pkg.id'],
                name='fk_pkg_folder_pkg_source_and_id',
            ),
        ],
    ) as batch_op:
        batch_op.drop_constraint('fk_pkg_folder_pkg_source_and_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_folder_pkg_source_and_id',
            'pkg',
            ['pkg_source', 'pkg_id'],
            ['source', 'id'],
            ondelete='CASCADE',
        )

    with op.batch_alter_table(
        'pkg_options',
        schema=None,
        reflect_args=[
            sa.ForeignKeyConstraint(
                ['pkg_source', 'pkg_id'],
                ['pkg.source', 'pkg.id'],
                name='fk_pkg_options_pkg_source_and_id',
            ),
        ],
    ) as batch_op:
        batch_op.drop_constraint('fk_pkg_options_pkg_source_and_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_options_pkg_source_and_id',
            'pkg',
            ['pkg_source', 'pkg_id'],
            ['source', 'id'],
            ondelete='CASCADE',
        )

    with op.batch_alter_table(
        'pkg_version_log',
        schema=None,
        reflect_args=[
            sa.ForeignKeyConstraint(
                ['pkg_source', 'pkg_id'],
                ['pkg.source', 'pkg.id'],
                name='fk_pkg_version_log_pkg_source_and_id',
            ),
        ],
    ) as batch_op:
        batch_op.drop_constraint('fk_pkg_version_log_pkg_source_and_id', type_='foreignkey')


def downgrade():
    with op.batch_alter_table('pkg_options', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pkg_options_pkg_source_and_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_options_pkg_source_and_id', 'pkg', ['pkg_source', 'pkg_id'], ['source', 'id']
        )

    with op.batch_alter_table('pkg_folder', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pkg_folder_pkg_source_and_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_folder_pkg_source_and_id', 'pkg', ['pkg_source', 'pkg_id'], ['source', 'id']
        )

    with op.batch_alter_table('pkg_dep', schema=None) as batch_op:
        batch_op.drop_constraint('fk_pkg_dep_pkg_source_and_id', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_pkg_dep_pkg_source_and_id', 'pkg', ['pkg_source', 'pkg_id'], ['source', 'id']
        )

    with op.batch_alter_table('pkg_version_log', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_pkg_version_log_pkg_source_and_id',
            'pkg',
            ['pkg_source', 'pkg_id'],
            ['source', 'id'],
        )
