"""Add benchmark_decisions table for forward agent-vs-baseline measurement

Revision ID: b8e2d4f6a913
Revises: f3a7c1b9d2e4
Create Date: 2026-08-28 02:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'b8e2d4f6a913'
down_revision: Union[str, None] = 'f3a7c1b9d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('benchmark_decisions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('strategy', sa.String(), nullable=False),
        sa.Column('ticker', sa.String(), nullable=False),
        sa.Column('action', sa.String(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('entry_price', sa.Float(), nullable=False),
        sa.Column('horizon_days', sa.Integer(), server_default='5'),
        sa.Column('resolved', sa.Boolean(), server_default=sa.false()),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('exit_price', sa.Float(), nullable=True),
        sa.Column('return_pct', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_benchmark_decisions_id'), 'benchmark_decisions', ['id'], unique=False)
    op.create_index(op.f('ix_benchmark_decisions_user_id'), 'benchmark_decisions', ['user_id'], unique=False)
    op.create_index(op.f('ix_benchmark_decisions_strategy'), 'benchmark_decisions', ['strategy'], unique=False)
    op.create_index(op.f('ix_benchmark_decisions_ticker'), 'benchmark_decisions', ['ticker'], unique=False)
    op.create_index(op.f('ix_benchmark_decisions_decided_at'), 'benchmark_decisions', ['decided_at'], unique=False)
    op.create_index(op.f('ix_benchmark_decisions_resolved'), 'benchmark_decisions', ['resolved'], unique=False)


def downgrade() -> None:
    for idx in (
        'ix_benchmark_decisions_resolved',
        'ix_benchmark_decisions_decided_at',
        'ix_benchmark_decisions_ticker',
        'ix_benchmark_decisions_strategy',
        'ix_benchmark_decisions_user_id',
        'ix_benchmark_decisions_id',
    ):
        op.drop_index(op.f(idx), table_name='benchmark_decisions')
    op.drop_table('benchmark_decisions')
