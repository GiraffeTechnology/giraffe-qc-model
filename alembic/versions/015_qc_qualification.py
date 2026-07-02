"""qc qualification, shadow mode, accuracy gate (PR 27)

Revision ID: 015
Revises: 014
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_qualification_datasets',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=True),
        sa.Column('station_id', sa.String(length=64), nullable=True),
        sa.Column('name', sa.String(length=256), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_qualification_datasets_tenant_id', 'qc_qualification_datasets', ['tenant_id'])
    op.create_index('ix_qc_qualification_datasets_training_pack_id', 'qc_qualification_datasets', ['training_pack_id'])

    op.create_table(
        'qc_qualification_samples',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('dataset_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_code', sa.String(length=64), nullable=False),
        sa.Column('sample_type', sa.String(length=32), nullable=False),
        sa.Column('image_reference', sa.String(length=1024), nullable=False),
        sa.Column('human_label', sa.String(length=16), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['dataset_id'], ['qc_qualification_datasets.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_qualification_samples_tenant_id', 'qc_qualification_samples', ['tenant_id'])
    op.create_index('ix_qc_qualification_samples_dataset_id', 'qc_qualification_samples', ['dataset_id'])
    op.create_index('ix_qc_qualification_samples_detection_point_code', 'qc_qualification_samples', ['detection_point_code'])

    op.create_table(
        'qc_qualification_runs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('dataset_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=128), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['dataset_id'], ['qc_qualification_datasets.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_qualification_runs_tenant_id', 'qc_qualification_runs', ['tenant_id'])
    op.create_index('ix_qc_qualification_runs_training_pack_id', 'qc_qualification_runs', ['training_pack_id'])

    op.create_table(
        'qc_qualification_results',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_code', sa.String(length=64), nullable=False),
        sa.Column('sample_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('defect_sample_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('boundary_sample_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('true_pass', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('true_fail', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('false_pass', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('false_fail', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('indeterminate', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('false_pass_rate', sa.Float(), nullable=False, server_default='0'),
        sa.Column('false_fail_rate', sa.Float(), nullable=False, server_default='0'),
        sa.Column('confusion_json', sa.JSON(), nullable=True),
        sa.Column('meets_thresholds', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('threshold_failures_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['run_id'], ['qc_qualification_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_qualification_results_tenant_id', 'qc_qualification_results', ['tenant_id'])
    op.create_index('ix_qc_qualification_results_run_id', 'qc_qualification_results', ['run_id'])

    op.create_table(
        'qc_qualification_reports',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('overall_meets_thresholds', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('qualified_detection_point_codes_json', sa.JSON(), nullable=True),
        sa.Column('thresholds_json', sa.JSON(), nullable=True),
        sa.Column('summary_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['run_id'], ['qc_qualification_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_qualification_reports_tenant_id', 'qc_qualification_reports', ['tenant_id'])
    op.create_index('ix_qc_qualification_reports_training_pack_id', 'qc_qualification_reports', ['training_pack_id'])

    op.create_table(
        'qc_qualification_approvals',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('report_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('decision', sa.String(length=32), nullable=False),
        sa.Column('approved_by', sa.String(length=128), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['report_id'], ['qc_qualification_reports.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_qualification_approvals_tenant_id', 'qc_qualification_approvals', ['tenant_id'])
    op.create_index('ix_qc_qualification_approvals_report_id', 'qc_qualification_approvals', ['report_id'])

    op.create_table(
        'qc_shadow_observations',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_code', sa.String(length=64), nullable=True),
        sa.Column('image_reference', sa.String(length=1024), nullable=True),
        sa.Column('model_disposition', sa.String(length=32), nullable=False),
        sa.Column('human_decision', sa.String(length=32), nullable=False),
        sa.Column('agrees', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('provider', sa.String(length=128), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_shadow_observations_tenant_id', 'qc_shadow_observations', ['tenant_id'])
    op.create_index('ix_qc_shadow_observations_training_pack_id', 'qc_shadow_observations', ['training_pack_id'])


def downgrade() -> None:
    op.drop_table('qc_shadow_observations')
    op.drop_table('qc_qualification_approvals')
    op.drop_table('qc_qualification_reports')
    op.drop_table('qc_qualification_results')
    op.drop_table('qc_qualification_runs')
    op.drop_table('qc_qualification_samples')
    op.drop_table('qc_qualification_datasets')
