"""QC SKU catalog tables: qc_sku_items, qc_standard_photos,
qc_inspection_requirements, qc_detection_points.

Revision ID: 002
Revises: 001
Create Date: 2026-06-22
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_sku_items',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('item_number', sa.String(128), nullable=False, index=True),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('category', sa.String(128)),
        sa.Column('description', sa.Text),
        sa.Column('status', sa.String(32), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_standard_photos',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('sku_id', sa.String(64), sa.ForeignKey('qc_sku_items.id'), nullable=False, index=True),
        sa.Column('image_url', sa.String(512)),
        sa.Column('local_path', sa.String(512)),
        sa.Column('thumbnail_url', sa.String(512)),
        sa.Column('angle', sa.String(64)),
        sa.Column('view_type', sa.String(64)),
        sa.Column('sha256', sa.String(64)),
        sa.Column('width_px', sa.Integer),
        sa.Column('height_px', sa.Integer),
        sa.Column('mime_type', sa.String(128)),
        sa.Column('is_primary', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_inspection_requirements',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('sku_id', sa.String(64), sa.ForeignKey('qc_sku_items.id'), nullable=False, index=True),
        sa.Column('code', sa.String(64), nullable=False),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('requirement_text', sa.Text, nullable=False),
        sa.Column('severity', sa.String(32), nullable=False, server_default='major'),
        sa.Column('pass_criteria', sa.Text),
        sa.Column('tolerance_json', sa.JSON),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_detection_points',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('sku_id', sa.String(64), sa.ForeignKey('qc_sku_items.id'), nullable=False, index=True),
        sa.Column('requirement_id', sa.String(64), sa.ForeignKey('qc_inspection_requirements.id'), index=True),
        sa.Column('point_code', sa.String(64), nullable=False),
        sa.Column('label', sa.String(256), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('roi_json', sa.JSON),
        sa.Column('expected_value', sa.String(256)),
        sa.Column('method_hint', sa.String(128)),
        sa.Column('severity', sa.String(32), nullable=False, server_default='major'),
        sa.Column('sort_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('qc_detection_points')
    op.drop_table('qc_inspection_requirements')
    op.drop_table('qc_standard_photos')
    op.drop_table('qc_sku_items')
