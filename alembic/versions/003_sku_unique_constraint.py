"""Add unique constraint on (tenant_id, item_number) in qc_sku_items.

Revision ID: 003
Revises: 002
Create Date: 2026-06-23
"""
from alembic import op

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('qc_sku_items', schema=None) as batch_op:
        batch_op.create_unique_constraint(
            'uq_sku_tenant_item_number',
            ['tenant_id', 'item_number'],
        )


def downgrade() -> None:
    with op.batch_alter_table('qc_sku_items', schema=None) as batch_op:
        batch_op.drop_constraint('uq_sku_tenant_item_number', type_='unique')
