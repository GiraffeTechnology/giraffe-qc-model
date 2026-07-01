"""qc checkpoint classifications (Phase 1 visual QC training engine)

Revision ID: 007
Revises: 006
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_checkpoint_classifications',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_id', sa.String(length=64), nullable=False),
        sa.Column('proposed_checkpoint_category', sa.String(length=48), nullable=False),
        sa.Column('confirmed_checkpoint_category', sa.String(length=48), nullable=True),
        sa.Column('category_confirmed_by', sa.String(length=128), nullable=True),
        sa.Column('category_confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('classification_rationale', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['sku_id'], ['qc_sku_items.id']),
        sa.ForeignKeyConstraint(['detection_point_id'], ['qc_detection_points.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('detection_point_id', name='uq_checkpoint_classification_dp'),
    )
    op.create_index(
        'ix_qc_checkpoint_classifications_tenant_id',
        'qc_checkpoint_classifications', ['tenant_id'],
    )
    op.create_index(
        'ix_qc_checkpoint_classifications_sku_id',
        'qc_checkpoint_classifications', ['sku_id'],
    )
    op.create_index(
        'ix_qc_checkpoint_classifications_detection_point_id',
        'qc_checkpoint_classifications', ['detection_point_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_qc_checkpoint_classifications_detection_point_id',
                  table_name='qc_checkpoint_classifications')
    op.drop_index('ix_qc_checkpoint_classifications_sku_id',
                  table_name='qc_checkpoint_classifications')
    op.drop_index('ix_qc_checkpoint_classifications_tenant_id',
                  table_name='qc_checkpoint_classifications')
    op.drop_table('qc_checkpoint_classifications')
