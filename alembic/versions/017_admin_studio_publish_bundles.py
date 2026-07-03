"""admin studio: detection point pass_criteria + signed publish bundles (S2)

Revision ID: 017
Revises: 016
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'qc_detection_points',
        sa.Column('pass_criteria', sa.Text(), nullable=True),
    )

    op.create_table(
        'qc_publish_bundles',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=False),
        sa.Column('standard_revision_id', sa.String(length=64), nullable=False),
        sa.Column('revision_no', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('level', sa.String(length=16), nullable=False, server_default='L2'),
        sa.Column('manifest_version', sa.String(length=32), nullable=False, server_default='studio-bundle-v1'),
        sa.Column('manifest_json', sa.JSON(), nullable=False),
        sa.Column('bundle_hash', sa.String(length=64), nullable=False),
        sa.Column('signature', sa.String(length=128), nullable=False),
        sa.Column('signature_algorithm', sa.String(length=32), nullable=False, server_default='HMAC-SHA256'),
        sa.Column('signing_key_id', sa.String(length=64), nullable=False, server_default='default'),
        sa.Column('detection_point_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('published_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_publish_bundles_tenant_id', 'qc_publish_bundles', ['tenant_id'])
    op.create_index('ix_qc_publish_bundles_sku_id', 'qc_publish_bundles', ['sku_id'])
    op.create_index('ix_qc_publish_bundles_standard_revision_id', 'qc_publish_bundles', ['standard_revision_id'])


def downgrade() -> None:
    op.drop_index('ix_qc_publish_bundles_standard_revision_id', table_name='qc_publish_bundles')
    op.drop_index('ix_qc_publish_bundles_sku_id', table_name='qc_publish_bundles')
    op.drop_index('ix_qc_publish_bundles_tenant_id', table_name='qc_publish_bundles')
    op.drop_table('qc_publish_bundles')
    op.drop_column('qc_detection_points', 'pass_criteria')
