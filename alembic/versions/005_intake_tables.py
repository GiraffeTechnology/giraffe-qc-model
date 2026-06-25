"""Add QC standard intake, intake media, and operator confirmation tables.

Revision ID: 005
Revises: 004
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_standard_intakes',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('sku_id', sa.String(64), sa.ForeignKey('qc_sku_items.id'),
                  nullable=False, index=True),
        sa.Column('source_type', sa.String(32), nullable=False, default='api'),
        sa.Column('source_channel', sa.String(64)),
        sa.Column('source_message_id', sa.String(256)),
        sa.Column('operator_id', sa.String(128)),
        sa.Column('raw_text', sa.Text),
        sa.Column('normalized_text', sa.Text),
        sa.Column('status', sa.String(32), nullable=False, default='received'),
        sa.Column('extracted_json', sa.JSON),
        sa.Column('confirmation_payload_json', sa.JSON),
        sa.Column('parser_version', sa.String(64)),
        sa.Column('confidence_score', sa.Float),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_intake_media',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('intake_id', sa.String(64), sa.ForeignKey('qc_standard_intakes.id'),
                  nullable=False, index=True),
        sa.Column('media_type', sa.String(32), nullable=False, default='image'),
        sa.Column('media_role', sa.String(64), nullable=False, default='standard_photo'),
        sa.Column('image_url', sa.String(512)),
        sa.Column('local_path', sa.String(512)),
        sa.Column('thumbnail_url', sa.String(512)),
        sa.Column('sha256', sa.String(64)),
        sa.Column('mime_type', sa.String(128)),
        sa.Column('width_px', sa.Integer),
        sa.Column('height_px', sa.Integer),
        sa.Column('duration_ms', sa.Integer),
        sa.Column('metadata_json', sa.JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_operator_confirmations',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('intake_id', sa.String(64), sa.ForeignKey('qc_standard_intakes.id'),
                  nullable=False, index=True),
        sa.Column('sku_id', sa.String(64), sa.ForeignKey('qc_sku_items.id'),
                  nullable=False, index=True),
        sa.Column('status', sa.String(32), nullable=False),
        sa.Column('confirmed_by', sa.String(128), nullable=False),
        sa.Column('confirmed_json', sa.JSON),
        sa.Column('operator_comment', sa.Text),
        sa.Column('created_standard_revision_id', sa.String(64),
                  sa.ForeignKey('qc_sku_standard_revisions.id'), index=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('qc_operator_confirmations')
    op.drop_table('qc_intake_media')
    op.drop_table('qc_standard_intakes')
