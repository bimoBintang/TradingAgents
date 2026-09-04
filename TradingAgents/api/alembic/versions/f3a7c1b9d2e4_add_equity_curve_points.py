"""Add equity_curve_points table for real, restart-proof max drawdown

Revision ID: f3a7c1b9d2e4
Revises: a1b2c3d4e5f6
Create Date: 2026-08-27 22:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'f3a7c1b9d2e4'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('equity_curve_points',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('equity', sa.Float(), nullable=False),
        sa.Column('recorded_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_equity_curve_points_id'), 'equity_curve_points', ['id'], unique=False)
    op.create_index(op.f('ix_equity_curve_points_user_id'), 'equity_curve_points', ['user_id'], unique=False)
    op.create_index(op.f('ix_equity_curve_points_recorded_at'), 'equity_curve_points', ['recorded_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_equity_curve_points_recorded_at'), table_name='equity_curve_points')
    op.drop_index(op.f('ix_equity_curve_points_user_id'), table_name='equity_curve_points')
    op.drop_index(op.f('ix_equity_curve_points_id'), table_name='equity_curve_points')
    op.drop_table('equity_curve_points')
