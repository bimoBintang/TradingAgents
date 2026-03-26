"""Add user_configs table for multi-tenant SaaS isolation

Revision ID: a1b2c3d4e5f6
Revises: 35c45d22f89b
Create Date: 2026-03-26 12:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '35c45d22f89b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('user_configs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('config_json', sa.Text(), nullable=False, server_default='{}'),
        sa.Column('encrypted_api_key', sa.String(), server_default=''),
        sa.Column('encrypted_api_secret', sa.String(), server_default=''),
        sa.Column('encrypted_password', sa.String(), server_default=''),
        sa.Column('config_version', sa.Integer(), server_default='1'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index(op.f('ix_user_configs_id'), 'user_configs', ['id'], unique=False)
    op.create_index(op.f('ix_user_configs_user_id'), 'user_configs', ['user_id'], unique=True)

    # ── Backfill: create UserConfig rows for existing users ──
    op.execute(
        "INSERT INTO user_configs (user_id, config_json, config_version) "
        "SELECT id, '{}', 1 FROM users "
        "WHERE id NOT IN (SELECT user_id FROM user_configs)"
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_user_configs_user_id'), table_name='user_configs')
    op.drop_index(op.f('ix_user_configs_id'), table_name='user_configs')
    op.drop_table('user_configs')
