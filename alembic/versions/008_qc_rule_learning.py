"""qc rule learning engine tables (Phase 2A)

Revision ID: 008
Revises: 007
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_learning_jobs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=False),
        sa.Column('station_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='draft'),
        sa.Column('runtime_profile', sa.String(length=32), nullable=False, server_default='server'),
        sa.Column('provider', sa.String(length=64), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_learning_jobs_tenant_id', 'qc_learning_jobs', ['tenant_id'])
    op.create_index('ix_qc_learning_jobs_training_pack_id', 'qc_learning_jobs', ['training_pack_id'])
    op.create_index('ix_qc_learning_jobs_sku_id', 'qc_learning_jobs', ['sku_id'])

    op.create_table(
        'qc_learning_inputs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('learning_job_id', sa.String(length=64), nullable=False),
        sa.Column('input_type', sa.String(length=32), nullable=False, server_default='operator_requirement'),
        sa.Column('source', sa.String(length=32), nullable=True),
        sa.Column('text_content', sa.Text(), nullable=True),
        sa.Column('sample_refs_json', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['learning_job_id'], ['qc_learning_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_learning_inputs_tenant_id', 'qc_learning_inputs', ['tenant_id'])
    op.create_index('ix_qc_learning_inputs_learning_job_id', 'qc_learning_inputs', ['learning_job_id'])

    op.create_table(
        'qc_learned_detection_point_proposals',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('learning_job_id', sa.String(length=64), nullable=False),
        sa.Column('source_requirement', sa.Text(), nullable=True),
        sa.Column('proposed_code', sa.String(length=64), nullable=False),
        sa.Column('proposed_name', sa.String(length=256), nullable=True),
        sa.Column('proposed_checkpoint_category', sa.String(length=48), nullable=False),
        sa.Column('proposed_ai_role', sa.String(length=48), nullable=False),
        sa.Column('target_region', sa.String(length=256), nullable=True),
        sa.Column('severity', sa.String(length=32), nullable=False, server_default='major'),
        sa.Column('normal_visual_features_json', sa.JSON(), nullable=True),
        sa.Column('defect_visual_features_json', sa.JSON(), nullable=True),
        sa.Column('known_pseudo_defects_json', sa.JSON(), nullable=True),
        sa.Column('decision_rule', sa.Text(), nullable=True),
        sa.Column('review_required_conditions_json', sa.JSON(), nullable=True),
        sa.Column('evidence_required', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('uncertainties_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='proposed'),
        sa.Column('approved_by', sa.String(length=128), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('applied_detection_point_id', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['learning_job_id'], ['qc_learning_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_learned_dp_proposals_tenant_id', 'qc_learned_detection_point_proposals', ['tenant_id'])
    op.create_index('ix_qc_learned_dp_proposals_job_id', 'qc_learned_detection_point_proposals', ['learning_job_id'])

    op.create_table(
        'qc_learned_visual_rule_proposals',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('learning_job_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_proposal_id', sa.String(length=64), nullable=True),
        sa.Column('rule_type', sa.String(length=48), nullable=False),
        sa.Column('rule_text', sa.Text(), nullable=False),
        sa.Column('source_samples_json', sa.JSON(), nullable=True),
        sa.Column('source_requirement', sa.Text(), nullable=True),
        sa.Column('provider', sa.String(length=64), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('runtime_profile', sa.String(length=32), nullable=False, server_default='server'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='proposed'),
        sa.Column('approved_by', sa.String(length=128), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['learning_job_id'], ['qc_learning_jobs.id']),
        sa.ForeignKeyConstraint(['detection_point_proposal_id'], ['qc_learned_detection_point_proposals.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_learned_rule_proposals_tenant_id', 'qc_learned_visual_rule_proposals', ['tenant_id'])
    op.create_index('ix_qc_learned_rule_proposals_job_id', 'qc_learned_visual_rule_proposals', ['learning_job_id'])
    op.create_index('ix_qc_learned_rule_proposals_dp_id', 'qc_learned_visual_rule_proposals', ['detection_point_proposal_id'])

    op.create_table(
        'qc_learning_approvals',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('learning_job_id', sa.String(length=64), nullable=False),
        sa.Column('proposal_type', sa.String(length=32), nullable=False),
        sa.Column('proposal_id', sa.String(length=64), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('edited_payload_json', sa.JSON(), nullable=True),
        sa.Column('reviewer_id', sa.String(length=128), nullable=True),
        sa.Column('review_comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['learning_job_id'], ['qc_learning_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_learning_approvals_tenant_id', 'qc_learning_approvals', ['tenant_id'])
    op.create_index('ix_qc_learning_approvals_job_id', 'qc_learning_approvals', ['learning_job_id'])
    op.create_index('ix_qc_learning_approvals_proposal_id', 'qc_learning_approvals', ['proposal_id'])

    op.create_table(
        'qc_learning_reports',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('learning_job_id', sa.String(length=64), nullable=False),
        sa.Column('report_json', sa.JSON(), nullable=True),
        sa.Column('requires_supervisor_review', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('can_apply_to_training_pack', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['learning_job_id'], ['qc_learning_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_learning_reports_tenant_id', 'qc_learning_reports', ['tenant_id'])
    op.create_index('ix_qc_learning_reports_job_id', 'qc_learning_reports', ['learning_job_id'])


def downgrade() -> None:
    op.drop_table('qc_learning_reports')
    op.drop_table('qc_learning_approvals')
    op.drop_table('qc_learned_visual_rule_proposals')
    op.drop_table('qc_learned_detection_point_proposals')
    op.drop_table('qc_learning_inputs')
    op.drop_table('qc_learning_jobs')
