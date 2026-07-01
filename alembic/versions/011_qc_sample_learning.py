"""qc vlm sample learning (PR 23)

Revision ID: 011
Revises: 010
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def _ts():
    return sa.text('CURRENT_TIMESTAMP')


def upgrade() -> None:
    op.create_table(
        'qc_sample_groups',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_code', sa.String(length=64), nullable=True),
        sa.Column('sample_type', sa.String(length=32), nullable=False),
        sa.Column('samples_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='draft'),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_sample_groups_tenant_id', 'qc_sample_groups', ['tenant_id'])
    op.create_index('ix_qc_sample_groups_training_pack_id', 'qc_sample_groups', ['training_pack_id'])
    op.create_index('ix_qc_sample_groups_detection_point_id', 'qc_sample_groups', ['detection_point_id'])

    op.create_table(
        'qc_sample_learning_jobs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('sample_group_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('provider', sa.String(length=128), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('observation_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['sample_group_id'], ['qc_sample_groups.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_sample_learning_jobs_tenant_id', 'qc_sample_learning_jobs', ['tenant_id'])
    op.create_index('ix_qc_sample_learning_jobs_training_pack_id', 'qc_sample_learning_jobs', ['training_pack_id'])
    op.create_index('ix_qc_sample_learning_jobs_sample_group_id', 'qc_sample_learning_jobs', ['sample_group_id'])

    op.create_table(
        'qc_visual_feature_observations',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('sample_learning_job_id', sa.String(length=64), nullable=False),
        sa.Column('sample_group_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_code', sa.String(length=64), nullable=True),
        sa.Column('source_sample_id', sa.String(length=64), nullable=False),
        sa.Column('image_reference', sa.String(length=1024), nullable=True),
        sa.Column('feature_type', sa.String(length=48), nullable=False),
        sa.Column('evidence_region_json', sa.JSON(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('uncertainty', sa.Text(), nullable=True),
        sa.Column('rule_implication', sa.Text(), nullable=True),
        sa.Column('requires_human_review', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('normal_visual_features_json', sa.JSON(), nullable=True),
        sa.Column('acceptable_variations_json', sa.JSON(), nullable=True),
        sa.Column('defect_visual_features_json', sa.JSON(), nullable=True),
        sa.Column('known_pseudo_defects_json', sa.JSON(), nullable=True),
        sa.Column('capture_artifact_risks_json', sa.JSON(), nullable=True),
        sa.Column('evidence_required_json', sa.JSON(), nullable=True),
        sa.Column('review_required_conditions_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.ForeignKeyConstraint(['sample_learning_job_id'], ['qc_sample_learning_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_vfo_tenant_id', 'qc_visual_feature_observations', ['tenant_id'])
    op.create_index('ix_qc_vfo_job_id', 'qc_visual_feature_observations', ['sample_learning_job_id'])
    op.create_index('ix_qc_vfo_source_sample_id', 'qc_visual_feature_observations', ['source_sample_id'])

    op.create_table(
        'qc_sample_evidence_anchors',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('observation_id', sa.String(length=64), nullable=False),
        sa.Column('source_sample_id', sa.String(length=64), nullable=False),
        sa.Column('image_reference', sa.String(length=1024), nullable=True),
        sa.Column('evidence_region_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.ForeignKeyConstraint(['observation_id'], ['qc_visual_feature_observations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_sea_tenant_id', 'qc_sample_evidence_anchors', ['tenant_id'])
    op.create_index('ix_qc_sea_observation_id', 'qc_sample_evidence_anchors', ['observation_id'])

    op.create_table(
        'qc_visual_rule_memory',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('sample_learning_job_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_code', sa.String(length=64), nullable=True),
        sa.Column('feature_type', sa.String(length=48), nullable=False),
        sa.Column('normal_visual_features_json', sa.JSON(), nullable=True),
        sa.Column('acceptable_variations_json', sa.JSON(), nullable=True),
        sa.Column('defect_visual_features_json', sa.JSON(), nullable=True),
        sa.Column('known_pseudo_defects_json', sa.JSON(), nullable=True),
        sa.Column('capture_artifact_risks_json', sa.JSON(), nullable=True),
        sa.Column('evidence_required_json', sa.JSON(), nullable=True),
        sa.Column('review_required_conditions_json', sa.JSON(), nullable=True),
        sa.Column('observation_ids_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='proposed'),
        sa.Column('approved_by', sa.String(length=128), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_comment', sa.Text(), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.ForeignKeyConstraint(['sample_learning_job_id'], ['qc_sample_learning_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_vrm_tenant_id', 'qc_visual_rule_memory', ['tenant_id'])
    op.create_index('ix_qc_vrm_job_id', 'qc_visual_rule_memory', ['sample_learning_job_id'])
    op.create_index('ix_qc_vrm_training_pack_id', 'qc_visual_rule_memory', ['training_pack_id'])
    op.create_index('ix_qc_vrm_detection_point_code', 'qc_visual_rule_memory', ['detection_point_code'])

    for table, extra in (
        ('qc_pseudo_defect_rules', [sa.Column('risk_level', sa.String(length=16), nullable=False, server_default='normal')]),
        ('qc_capture_artifact_rules', []),
    ):
        op.create_table(
            table,
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('tenant_id', sa.String(length=64), nullable=False),
            sa.Column('training_pack_id', sa.String(length=64), nullable=False),
            sa.Column('visual_rule_memory_id', sa.String(length=64), nullable=False),
            sa.Column('detection_point_code', sa.String(length=64), nullable=True),
            sa.Column('pattern_text', sa.Text(), nullable=False),
            *extra,
            sa.Column('source_sample_id', sa.String(length=64), nullable=True),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='proposed'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
            sa.ForeignKeyConstraint(['visual_rule_memory_id'], ['qc_visual_rule_memory.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'])
        op.create_index(f'ix_{table}_memory_id', table, ['visual_rule_memory_id'])

    op.create_table(
        'qc_confirmed_visual_rules',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_code', sa.String(length=64), nullable=True),
        sa.Column('feature_type', sa.String(length=48), nullable=False),
        sa.Column('content_json', sa.JSON(), nullable=True),
        sa.Column('source_memory_id', sa.String(length=64), nullable=False),
        sa.Column('confirmed_by', sa.String(length=128), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_ts()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_cvr_tenant_id', 'qc_confirmed_visual_rules', ['tenant_id'])
    op.create_index('ix_qc_cvr_training_pack_id', 'qc_confirmed_visual_rules', ['training_pack_id'])
    op.create_index('ix_qc_cvr_detection_point_code', 'qc_confirmed_visual_rules', ['detection_point_code'])


def downgrade() -> None:
    op.drop_table('qc_confirmed_visual_rules')
    op.drop_table('qc_capture_artifact_rules')
    op.drop_table('qc_pseudo_defect_rules')
    op.drop_table('qc_visual_rule_memory')
    op.drop_table('qc_sample_evidence_anchors')
    op.drop_table('qc_visual_feature_observations')
    op.drop_table('qc_sample_learning_jobs')
    op.drop_table('qc_sample_groups')
