"""Initial schema: sample_items, qc_tasks, qc_results, video_tasks, capture_records.

Revision ID: 001
Revises:
Create Date: 2025-06-17
"""
from alembic import op
import sqlalchemy as sa

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sample_items',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('sku_id', sa.String(128), nullable=False, index=True),
        sa.Column('product_name', sa.String(256)),
        sa.Column('image_path', sa.String(512), nullable=False),
        sa.Column('version', sa.Integer, nullable=False, server_default='1'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='1'),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notes', sa.Text),
    )

    op.create_table(
        'qc_tasks',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('sample_id', sa.Integer, sa.ForeignKey('sample_items.id'), nullable=False),
        sa.Column('source_image_path', sa.String(512), nullable=False),
        sa.Column('source_type', sa.String(32), nullable=False, server_default='manual'),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
    )

    op.create_table(
        'qc_results',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('task_id', sa.Integer, sa.ForeignKey('qc_tasks.id'), nullable=False, unique=True),
        sa.Column('llm_provider', sa.String(32), nullable=False),
        sa.Column('model_name', sa.String(128), nullable=False),
        sa.Column('http_status', sa.Integer, nullable=False),
        sa.Column('elapsed_ms', sa.Integer, nullable=False),
        sa.Column('overall_result', sa.String(32), nullable=False),
        sa.Column('similarity_score', sa.Float, server_default='0.0'),
        sa.Column('severity', sa.String(32)),
        sa.Column('feedback_zh', sa.Text),
        sa.Column('feedback_en', sa.Text),
        sa.Column('deviations', sa.JSON),
        sa.Column('llm_raw_summary', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'video_tasks',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('video_path', sa.String(512), nullable=False),
        sa.Column('sku_id', sa.String(128), index=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('total_frames', sa.Integer, server_default='0'),
        sa.Column('tier1_filtered', sa.Integer, server_default='0'),
        sa.Column('tier2_processed', sa.Integer, server_default='0'),
        sa.Column('tier2_passed', sa.Integer, server_default='0'),
        sa.Column('tier3_llm_called', sa.Integer, server_default='0'),
        sa.Column('llm_save_ratio', sa.Float, server_default='0.0'),
    )

    op.create_table(
        'capture_records',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('video_task_id', sa.Integer, sa.ForeignKey('video_tasks.id'), nullable=False),
        sa.Column('frame_index', sa.Integer, nullable=False),
        sa.Column('frame_timestamp_ms', sa.Integer, nullable=False),
        sa.Column('frame_path', sa.String(512), nullable=False),
        sa.Column('tier2_score', sa.Float, nullable=False),
        sa.Column('qc_task_id', sa.Integer, sa.ForeignKey('qc_tasks.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('capture_records')
    op.drop_table('video_tasks')
    op.drop_table('qc_results')
    op.drop_table('qc_tasks')
    op.drop_table('sample_items')
