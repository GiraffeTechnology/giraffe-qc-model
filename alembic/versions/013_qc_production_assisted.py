"""qc production assisted mode (PR 25)

Revision ID: 013
Revises: 012
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_production_sessions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=True),
        sa.Column('station_id', sa.String(length=64), nullable=True),
        sa.Column('operator_id', sa.String(length=128), nullable=True),
        sa.Column('production_mode', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('readiness_snapshot_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_production_sessions_tenant_id', 'qc_production_sessions', ['tenant_id'])
    op.create_index('ix_qc_production_sessions_training_pack_id', 'qc_production_sessions', ['training_pack_id'])

    op.create_table(
        'qc_production_captures',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('image_reference', sa.String(length=1024), nullable=False),
        sa.Column('capture_metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['session_id'], ['qc_production_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_production_captures_tenant_id', 'qc_production_captures', ['tenant_id'])
    op.create_index('ix_qc_production_captures_session_id', 'qc_production_captures', ['session_id'])

    op.create_table(
        'qc_production_runs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('provider', sa.String(length=128), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('prompt_schema_version', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('overall_disposition', sa.String(length=32), nullable=True),
        sa.Column('detection_result_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['qc_production_sessions.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_production_runs_tenant_id', 'qc_production_runs', ['tenant_id'])
    op.create_index('ix_qc_production_runs_session_id', 'qc_production_runs', ['session_id'])
    op.create_index('ix_qc_production_runs_training_pack_id', 'qc_production_runs', ['training_pack_id'])

    op.create_table(
        'qc_production_detection_results',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('detection_point_code', sa.String(length=64), nullable=True),
        sa.Column('confirmed_visual_rule_id', sa.String(length=64), nullable=True),
        sa.Column('visual_rule_memory_id', sa.String(length=64), nullable=True),
        sa.Column('checkpoint_category', sa.String(length=48), nullable=True),
        sa.Column('disposition', sa.String(length=32), nullable=False),
        sa.Column('observed_features_json', sa.JSON(), nullable=True),
        sa.Column('defect_features_json', sa.JSON(), nullable=True),
        sa.Column('normal_features_matched_json', sa.JSON(), nullable=True),
        sa.Column('evidence_regions_json', sa.JSON(), nullable=True),
        sa.Column('review_required_conditions_json', sa.JSON(), nullable=True),
        sa.Column('source_image_reference', sa.String(length=1024), nullable=True),
        sa.Column('capture_metadata_json', sa.JSON(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('uncertainty', sa.Text(), nullable=True),
        sa.Column('provider', sa.String(length=128), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('prompt_schema_version', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['run_id'], ['qc_production_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_production_detection_results_tenant_id', 'qc_production_detection_results', ['tenant_id'])
    op.create_index('ix_qc_production_detection_results_run_id', 'qc_production_detection_results', ['run_id'])

    op.create_table(
        'qc_production_evidence_packets',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('packet_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['run_id'], ['qc_production_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_production_evidence_packets_tenant_id', 'qc_production_evidence_packets', ['tenant_id'])
    op.create_index('ix_qc_production_evidence_packets_run_id', 'qc_production_evidence_packets', ['run_id'])

    op.create_table(
        'qc_production_final_decisions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('run_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('decision', sa.String(length=32), nullable=False),
        sa.Column('decided_by', sa.String(length=128), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('recommended_disposition', sa.String(length=32), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['run_id'], ['qc_production_runs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_production_final_decisions_tenant_id', 'qc_production_final_decisions', ['tenant_id'])
    op.create_index('ix_qc_production_final_decisions_run_id', 'qc_production_final_decisions', ['run_id'])


def downgrade() -> None:
    op.drop_table('qc_production_final_decisions')
    op.drop_table('qc_production_evidence_packets')
    op.drop_table('qc_production_detection_results')
    op.drop_table('qc_production_runs')
    op.drop_table('qc_production_captures')
    op.drop_table('qc_production_sessions')
