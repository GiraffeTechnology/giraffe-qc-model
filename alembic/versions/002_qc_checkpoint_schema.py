"""QC checkpoint-driven inspection system: 18 new tables.

Revision ID: 002
Revises: 001
Create Date: 2026-06-24
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_product_sku',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('sku_code', sa.String(128), nullable=False, unique=True),
        sa.Column('product_name', sa.String(256), nullable=False),
        sa.Column('category', sa.String(128)),
        sa.Column('supplier_id', sa.Integer),
        sa.Column('customer_id', sa.Integer),
        sa.Column('status', sa.String(32), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_product_sku_sku_code', 'qc_product_sku', ['sku_code'], unique=True)

    op.create_table(
        'qc_channel_message',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('channel_type', sa.String(32), nullable=False),
        sa.Column('channel_message_id', sa.String(256)),
        sa.Column('sender_id', sa.String(128)),
        sa.Column('sender_name', sa.String(256)),
        sa.Column('raw_text', sa.Text),
        sa.Column('normalized_text', sa.Text),
        sa.Column('message_type', sa.String(32), nullable=False, server_default='text'),
        sa.Column('received_at', sa.DateTime(timezone=True)),
        sa.Column('processing_status', sa.String(32), nullable=False, server_default='received'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_channel_message_channel_message_id', 'qc_channel_message', ['channel_message_id'])

    op.create_table(
        'qc_media_asset',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('media_type', sa.String(32), nullable=False),
        sa.Column('media_role', sa.String(64), nullable=False),
        sa.Column('storage_uri', sa.String(512), nullable=False),
        sa.Column('thumbnail_uri', sa.String(512)),
        sa.Column('sha256', sa.String(64)),
        sa.Column('file_size', sa.Integer),
        sa.Column('mime_type', sa.String(128)),
        sa.Column('width', sa.Integer),
        sa.Column('height', sa.Integer),
        sa.Column('exif_json', sa.JSON),
        sa.Column('capture_device', sa.String(256)),
        sa.Column('color_temperature', sa.String(64)),
        sa.Column('lens_correction_applied', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('uploaded_by', sa.String(128)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_media_asset_sha256', 'qc_media_asset', ['sha256'])

    op.create_table(
        'qc_standard_intake',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('sku_id', sa.Integer, sa.ForeignKey('qc_product_sku.id'), nullable=False),
        sa.Column('source_channel_message_id', sa.Integer, sa.ForeignKey('qc_channel_message.id')),
        sa.Column('source_type', sa.String(32), nullable=False, server_default='web'),
        sa.Column('operator_id', sa.String(128)),
        sa.Column('intake_status', sa.String(32), nullable=False, server_default='draft'),
        sa.Column('parser_version', sa.String(32)),
        sa.Column('extracted_json', sa.JSON),
        sa.Column('confidence_score', sa.Float),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_standard_intake_sku_id', 'qc_standard_intake', ['sku_id'])

    op.create_table(
        'qc_operator_confirmation',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('standard_intake_id', sa.Integer, sa.ForeignKey('qc_standard_intake.id'), nullable=False),
        sa.Column('confirmation_message_id', sa.Integer, sa.ForeignKey('qc_channel_message.id')),
        sa.Column('confirmed_by', sa.String(128)),
        sa.Column('confirmation_status', sa.String(32), nullable=False),
        sa.Column('confirmed_json', sa.JSON),
        sa.Column('operator_comment', sa.Text),
        sa.Column('confirmed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_operator_confirmation_standard_intake_id', 'qc_operator_confirmation', ['standard_intake_id'])

    op.create_table(
        'qc_standard_version',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('sku_id', sa.Integer, sa.ForeignKey('qc_product_sku.id'), nullable=False),
        sa.Column('version_no', sa.String(32), nullable=False),
        sa.Column('standard_name', sa.String(256), nullable=False),
        sa.Column('standard_status', sa.String(32), nullable=False, server_default='active'),
        sa.Column('source_intake_id', sa.Integer, sa.ForeignKey('qc_standard_intake.id')),
        sa.Column('approved_by', sa.String(128)),
        sa.Column('approved_at', sa.DateTime(timezone=True)),
        sa.Column('effective_from', sa.DateTime(timezone=True)),
        sa.Column('effective_to', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_standard_version_sku_id', 'qc_standard_version', ['sku_id'])

    op.create_table(
        'qc_standard_media',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('standard_version_id', sa.Integer, sa.ForeignKey('qc_standard_version.id'), nullable=False),
        sa.Column('media_asset_id', sa.Integer, sa.ForeignKey('qc_media_asset.id'), nullable=False),
        sa.Column('view_type', sa.String(64), nullable=False, server_default='front'),
        sa.Column('is_primary', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('description', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_standard_media_standard_version_id', 'qc_standard_media', ['standard_version_id'])

    op.create_table(
        'qc_check_point',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('standard_version_id', sa.Integer, sa.ForeignKey('qc_standard_version.id'), nullable=False),
        sa.Column('checkpoint_code', sa.String(64), nullable=False),
        sa.Column('checkpoint_name', sa.String(256), nullable=False),
        sa.Column('target_part', sa.String(256)),
        sa.Column('inspection_method', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(32), nullable=False, server_default='major'),
        sa.Column('pass_rule_text', sa.Text),
        sa.Column('rule_json', sa.JSON),
        sa.Column('requires_human_review', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('display_order', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_check_point_standard_version_id', 'qc_check_point', ['standard_version_id'])

    op.create_table(
        'qc_check_rule',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('checkpoint_id', sa.Integer, sa.ForeignKey('qc_check_point.id'), nullable=False),
        sa.Column('rule_type', sa.String(64), nullable=False),
        sa.Column('expected_value_json', sa.JSON),
        sa.Column('threshold_json', sa.JSON),
        sa.Column('fail_condition_json', sa.JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_check_rule_checkpoint_id', 'qc_check_rule', ['checkpoint_id'])

    op.create_table(
        'qc_inspection_job',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('sku_id', sa.Integer, sa.ForeignKey('qc_product_sku.id'), nullable=False),
        sa.Column('standard_version_id', sa.Integer, sa.ForeignKey('qc_standard_version.id'), nullable=False),
        sa.Column('batch_no', sa.String(128)),
        sa.Column('operator_id', sa.String(128)),
        sa.Column('inspection_status', sa.String(32), nullable=False, server_default='created'),
        sa.Column('runtime_type', sa.String(32), nullable=False, server_default='server_model'),
        sa.Column('checkpoint_total', sa.Integer, nullable=False, server_default='0'),
        sa.Column('checkpoint_observed_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('checkpoint_pass_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('checkpoint_fail_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('checkpoint_review_required_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('coverage_rate', sa.Float, nullable=False, server_default='0.0'),
        sa.Column('has_unchecked_checkpoint', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('incidental_finding_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('major_incidental_finding_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('critical_incidental_finding_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_inspection_job_sku_id', 'qc_inspection_job', ['sku_id'])
    op.create_index('ix_qc_inspection_job_standard_version_id', 'qc_inspection_job', ['standard_version_id'])

    op.create_table(
        'qc_inspection_media',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('inspection_job_id', sa.Integer, sa.ForeignKey('qc_inspection_job.id'), nullable=False),
        sa.Column('media_asset_id', sa.Integer, sa.ForeignKey('qc_media_asset.id'), nullable=False),
        sa.Column('view_type', sa.String(64), nullable=False, server_default='front'),
        sa.Column('is_primary', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_inspection_media_inspection_job_id', 'qc_inspection_media', ['inspection_job_id'])

    op.create_table(
        'qc_model_result',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('inspection_job_id', sa.Integer, sa.ForeignKey('qc_inspection_job.id'), nullable=False),
        sa.Column('model_name', sa.String(128)),
        sa.Column('model_version', sa.String(32)),
        sa.Column('runtime_type', sa.String(32), nullable=False, server_default='server_model'),
        sa.Column('overall_result', sa.String(32), nullable=False),
        sa.Column('overall_confidence', sa.Float),
        sa.Column('no_guess_policy_applied', sa.Boolean, nullable=False, server_default='1'),
        sa.Column('unsupported_checkpoints_json', sa.JSON),
        sa.Column('low_confidence_checkpoints_json', sa.JSON),
        sa.Column('manual_review_reason', sa.Text),
        sa.Column('raw_output_json', sa.JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_model_result_inspection_job_id', 'qc_model_result', ['inspection_job_id'])

    op.create_table(
        'qc_checkpoint_result',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('inspection_job_id', sa.Integer, sa.ForeignKey('qc_inspection_job.id'), nullable=False),
        sa.Column('checkpoint_id', sa.Integer, sa.ForeignKey('qc_check_point.id'), nullable=False),
        sa.Column('checkpoint_code', sa.String(64), nullable=False),
        sa.Column('checkpoint_name', sa.String(256), nullable=False),
        sa.Column('expected_json', sa.JSON),
        sa.Column('observed_json', sa.JSON),
        sa.Column('comparison_json', sa.JSON),
        sa.Column('result', sa.String(32), nullable=False),
        sa.Column('confidence_score', sa.Float),
        sa.Column('evidence_type', sa.String(32), nullable=False, server_default='none'),
        sa.Column('evidence_json', sa.JSON),
        sa.Column('evidence_media_id', sa.Integer, sa.ForeignKey('qc_media_asset.id')),
        sa.Column('verification_status', sa.String(32), nullable=False, server_default='observed'),
        sa.Column('failure_reason', sa.Text),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_checkpoint_result_inspection_job_id', 'qc_checkpoint_result', ['inspection_job_id'])
    op.create_index('ix_qc_checkpoint_result_checkpoint_id', 'qc_checkpoint_result', ['checkpoint_id'])

    op.create_table(
        'qc_incidental_finding',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('inspection_job_id', sa.Integer, sa.ForeignKey('qc_inspection_job.id'), nullable=False),
        sa.Column('media_asset_id', sa.Integer, sa.ForeignKey('qc_media_asset.id')),
        sa.Column('finding_type', sa.String(64), nullable=False),
        sa.Column('target_part', sa.String(128)),
        sa.Column('finding_text', sa.Text),
        sa.Column('severity', sa.String(32), nullable=False, server_default='minor'),
        sa.Column('confidence_score', sa.Float),
        sa.Column('is_within_approved_checklist', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('requires_human_review', sa.Boolean, nullable=False, server_default='0'),
        sa.Column('evidence_json', sa.JSON),
        sa.Column('evidence_media_id', sa.Integer, sa.ForeignKey('qc_media_asset.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_incidental_finding_inspection_job_id', 'qc_incidental_finding', ['inspection_job_id'])

    op.create_table(
        'qc_human_review',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('inspection_job_id', sa.Integer, sa.ForeignKey('qc_inspection_job.id'), nullable=False),
        sa.Column('reviewer_id', sa.String(128)),
        sa.Column('review_status', sa.String(32), nullable=False),
        sa.Column('original_result', sa.String(32)),
        sa.Column('final_result', sa.String(32), nullable=False),
        sa.Column('review_comment', sa.Text),
        sa.Column('reviewed_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_human_review_inspection_job_id', 'qc_human_review', ['inspection_job_id'])

    op.create_table(
        'qc_final_report',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('inspection_job_id', sa.Integer, sa.ForeignKey('qc_inspection_job.id'), nullable=False),
        sa.Column('report_status', sa.String(32), nullable=False, server_default='draft'),
        sa.Column('final_result', sa.String(32), nullable=False),
        sa.Column('summary_text', sa.Text),
        sa.Column('report_json', sa.JSON),
        sa.Column('report_uri', sa.String(512)),
        sa.Column('generated_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_final_report_inspection_job_id', 'qc_final_report', ['inspection_job_id'])

    op.create_table(
        'qc_training_sample',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('inspection_job_id', sa.Integer, sa.ForeignKey('qc_inspection_job.id'), nullable=False),
        sa.Column('media_asset_id', sa.Integer, sa.ForeignKey('qc_media_asset.id')),
        sa.Column('checkpoint_id', sa.Integer, sa.ForeignKey('qc_check_point.id')),
        sa.Column('sample_type', sa.String(32), nullable=False),
        sa.Column('label_json', sa.JSON),
        sa.Column('source', sa.String(32), nullable=False, server_default='ai_result'),
        sa.Column('quality_score', sa.Float),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_training_sample_inspection_job_id', 'qc_training_sample', ['inspection_job_id'])

    op.create_table(
        'qc_audit_event',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('entity_type', sa.String(64), nullable=False),
        sa.Column('entity_id', sa.Integer, nullable=False),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('actor_id', sa.String(128)),
        sa.Column('event_json', sa.JSON),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_qc_audit_event_entity_type', 'qc_audit_event', ['entity_type'])
    op.create_index('ix_qc_audit_event_entity_id', 'qc_audit_event', ['entity_id'])
    op.create_index('ix_qc_audit_event_event_type', 'qc_audit_event', ['event_type'])


def downgrade() -> None:
    op.drop_table('qc_audit_event')
    op.drop_table('qc_training_sample')
    op.drop_table('qc_final_report')
    op.drop_table('qc_human_review')
    op.drop_table('qc_incidental_finding')
    op.drop_table('qc_checkpoint_result')
    op.drop_table('qc_model_result')
    op.drop_table('qc_inspection_media')
    op.drop_table('qc_inspection_job')
    op.drop_table('qc_check_rule')
    op.drop_table('qc_check_point')
    op.drop_table('qc_standard_media')
    op.drop_table('qc_standard_version')
    op.drop_table('qc_operator_confirmation')
    op.drop_table('qc_standard_intake')
    op.drop_table('qc_media_asset')
    op.drop_table('qc_channel_message')
    op.drop_table('qc_product_sku')
