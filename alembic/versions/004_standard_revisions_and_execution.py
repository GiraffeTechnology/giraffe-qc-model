"""Add standard revision lifecycle and inspection execution tables.

Revision ID: 004
Revises: 003
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # qc_sku_standard_revisions
    op.create_table(
        'qc_sku_standard_revisions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('sku_id', sa.String(64), sa.ForeignKey('qc_sku_items.id'), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('revision_no', sa.Integer, nullable=False, default=1),
        sa.Column('status', sa.String(32), nullable=False, default='draft'),
        sa.Column('created_from', sa.String(32), nullable=False, default='admin_ui'),
        sa.Column('confirmed_by', sa.String(128)),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)),
        sa.Column('updated_by_operator', sa.String(128)),
        sa.Column('last_update_reason', sa.Text),
        sa.Column('superseded_by_revision', sa.Integer),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    # Add standard_revision_id FK to existing catalog tables (nullable for compat)
    with op.batch_alter_table('qc_standard_photos') as batch_op:
        batch_op.add_column(sa.Column('standard_revision_id', sa.String(64), nullable=True))
        batch_op.create_foreign_key(
            'fk_std_photo_revision', 'qc_sku_standard_revisions', ['standard_revision_id'], ['id']
        )
        batch_op.create_index('ix_qc_standard_photos_standard_revision_id', ['standard_revision_id'])

    with op.batch_alter_table('qc_inspection_requirements') as batch_op:
        batch_op.add_column(sa.Column('standard_revision_id', sa.String(64), nullable=True))
        batch_op.create_foreign_key(
            'fk_insp_req_revision', 'qc_sku_standard_revisions', ['standard_revision_id'], ['id']
        )
        batch_op.create_index('ix_qc_inspection_requirements_standard_revision_id', ['standard_revision_id'])

    with op.batch_alter_table('qc_detection_points') as batch_op:
        batch_op.add_column(sa.Column('standard_revision_id', sa.String(64), nullable=True))
        batch_op.create_foreign_key(
            'fk_detect_point_revision', 'qc_sku_standard_revisions', ['standard_revision_id'], ['id']
        )
        batch_op.create_index('ix_qc_detection_points_standard_revision_id', ['standard_revision_id'])

    # Inspection execution tables
    op.create_table(
        'qc_inspection_jobs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('sku_id', sa.String(64), sa.ForeignKey('qc_sku_items.id'), nullable=False, index=True),
        sa.Column('active_standard_revision_id', sa.String(64),
                  sa.ForeignKey('qc_sku_standard_revisions.id'), nullable=False, index=True),
        sa.Column('job_ref', sa.String(128), index=True),
        sa.Column('status', sa.String(32), nullable=False, default='pending'),
        sa.Column('created_by', sa.String(128)),
        sa.Column('notes', sa.Text),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_inspection_media',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('job_id', sa.String(64), sa.ForeignKey('qc_inspection_jobs.id'), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('image_url', sa.String(512)),
        sa.Column('local_path', sa.String(512)),
        sa.Column('angle', sa.String(64)),
        sa.Column('view_type', sa.String(64)),
        sa.Column('sha256', sa.String(64)),
        sa.Column('width_px', sa.Integer),
        sa.Column('height_px', sa.Integer),
        sa.Column('mime_type', sa.String(128)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_model_results',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('job_id', sa.String(64), sa.ForeignKey('qc_inspection_jobs.id'), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('media_id', sa.String(64), sa.ForeignKey('qc_inspection_media.id'), index=True),
        sa.Column('provider', sa.String(64), nullable=False),
        sa.Column('model_name', sa.String(128), nullable=False),
        sa.Column('http_status', sa.Integer),
        sa.Column('elapsed_ms', sa.Integer),
        sa.Column('raw_output', sa.JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_checkpoint_results',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('job_id', sa.String(64), sa.ForeignKey('qc_inspection_jobs.id'), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('detection_point_id', sa.String(64),
                  sa.ForeignKey('qc_detection_points.id'), nullable=False, index=True),
        sa.Column('model_result_id', sa.String(64), sa.ForeignKey('qc_model_results.id'), index=True),
        sa.Column('result', sa.String(32), nullable=False),
        sa.Column('observed_value', sa.String(256)),
        sa.Column('confidence', sa.Float, nullable=False, default=1.0),
        sa.Column('notes', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('job_id', 'detection_point_id', name='uq_checkpoint_result_job_point'),
    )

    op.create_table(
        'qc_incidental_findings',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('job_id', sa.String(64), sa.ForeignKey('qc_inspection_jobs.id'), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('description', sa.Text, nullable=False),
        sa.Column('severity', sa.String(32), nullable=False, default='minor'),
        sa.Column('location_hint', sa.String(256)),
        sa.Column('evidence_json', sa.JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_final_reports',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('job_id', sa.String(64), sa.ForeignKey('qc_inspection_jobs.id'),
                  nullable=False, unique=True, index=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('overall_result', sa.String(32), nullable=False),
        sa.Column('summary_text', sa.Text),
        sa.Column('checkpoint_results_count', sa.Integer, nullable=False, default=0),
        sa.Column('findings_count', sa.Integer, nullable=False, default=0),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_human_reviews',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('job_id', sa.String(64), sa.ForeignKey('qc_inspection_jobs.id'), nullable=False, index=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('reviewer_id', sa.String(128), nullable=False),
        sa.Column('decision', sa.String(32), nullable=False),
        sa.Column('notes', sa.Text),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        'qc_audit_events',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, index=True),
        sa.Column('entity_type', sa.String(32), nullable=False, index=True),
        sa.Column('entity_id', sa.String(64), nullable=False, index=True),
        sa.Column('event_type', sa.String(64), nullable=False, index=True),
        sa.Column('actor', sa.String(128)),
        sa.Column('details_json', sa.JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('qc_audit_events')
    op.drop_table('qc_human_reviews')
    op.drop_table('qc_final_reports')
    op.drop_table('qc_incidental_findings')
    op.drop_table('qc_checkpoint_results')
    op.drop_table('qc_model_results')
    op.drop_table('qc_inspection_media')
    op.drop_table('qc_inspection_jobs')

    with op.batch_alter_table('qc_detection_points') as batch_op:
        batch_op.drop_index('ix_qc_detection_points_standard_revision_id')
        batch_op.drop_constraint('fk_detect_point_revision', type_='foreignkey')
        batch_op.drop_column('standard_revision_id')

    with op.batch_alter_table('qc_inspection_requirements') as batch_op:
        batch_op.drop_index('ix_qc_inspection_requirements_standard_revision_id')
        batch_op.drop_constraint('fk_insp_req_revision', type_='foreignkey')
        batch_op.drop_column('standard_revision_id')

    with op.batch_alter_table('qc_standard_photos') as batch_op:
        batch_op.drop_index('ix_qc_standard_photos_standard_revision_id')
        batch_op.drop_constraint('fk_std_photo_revision', type_='foreignkey')
        batch_op.drop_column('standard_revision_id')

    op.drop_table('qc_sku_standard_revisions')
