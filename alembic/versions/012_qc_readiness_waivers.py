"""qc readiness waivers (PR 24)

Revision ID: 012
Revises: 011
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_readiness_waivers',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('check_id', sa.String(length=64), nullable=False),
        sa.Column('item_key', sa.String(length=256), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('supervisor_id', sa.String(length=128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_readiness_waivers_tenant_id', 'qc_readiness_waivers', ['tenant_id'])
    op.create_index('ix_qc_readiness_waivers_training_pack_id', 'qc_readiness_waivers', ['training_pack_id'])
    op.create_index('ix_qc_readiness_waivers_item_key', 'qc_readiness_waivers', ['item_key'])


def downgrade() -> None:
    op.drop_table('qc_readiness_waivers')
