"""Renovate ``pkg_options``.

Revision ID: 98716a7301f8
Revises: e13430219249
Create Date: 2022-10-23 16:18:51.169154

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = '98716a7301f8'
down_revision = 'e13430219249'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pkg_options', schema=None) as batch_op:
        batch_op.add_column(sa.Column('any_flavour', sa.Boolean()))
        batch_op.add_column(sa.Column('any_release_type', sa.Boolean()))
        batch_op.add_column(sa.Column('version_eq', sa.Boolean()))

    pkg_options = sa.table(
        'pkg_options',
        sa.column('any_flavour', sa.Boolean),
        sa.column('any_release_type', sa.Boolean),
        sa.column('version_eq', sa.Boolean),
        sa.column('strategy', sa.String),
    )

    conn = op.get_bind()
    conn.execute(
        sa.update(pkg_options)
        .where(pkg_options.c.strategy == sa.bindparam('strategy_'))
        .values(
            any_flavour=sa.bindparam('any_flavour'),
            any_release_type=sa.bindparam('any_release_type'),
            version_eq=sa.bindparam('version_eq'),
        ),
        [
            {
                'strategy_': 'default',
                'any_flavour': False,
                'any_release_type': False,
                'version_eq': False,
            },
            {
                'strategy_': 'latest',
                'any_flavour': False,
                'any_release_type': True,
                'version_eq': False,
            },
            {
                'strategy_': 'any_flavour',
                'any_flavour': True,
                'any_release_type': False,
                'version_eq': False,
            },
            {
                'strategy_': 'version',
                'any_flavour': False,
                'any_release_type': False,
                'version_eq': True,
            },
        ],
    )

    with op.batch_alter_table('pkg_options', schema=None) as batch_op:
        batch_op.alter_column('any_flavour', nullable=False)
        batch_op.alter_column('any_release_type', nullable=False)
        batch_op.alter_column('version_eq', nullable=False)
        batch_op.drop_column('strategy')


def downgrade():
    with op.batch_alter_table('pkg_options', schema=None) as batch_op:
        batch_op.add_column(sa.Column('strategy', sa.String(), nullable=False))
        batch_op.drop_column('version_eq')
        batch_op.drop_column('any_release_type')
        batch_op.drop_column('any_flavour')
