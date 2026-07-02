"""qc false-pass incident response & requalification (PR 28)

Revision ID: 016
Revises: 015
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_quality_incidents',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('incident_type', sa.String(length=48), nullable=False),
        sa.Column('severity', sa.String(length=8), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=True),
        sa.Column('station_id', sa.String(length=64), nullable=True),
        sa.Column('detection_point_code', sa.String(length=64), nullable=True),
        sa.Column('provider', sa.String(length=128), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('inspection_session_id', sa.String(length=64), nullable=True),
        sa.Column('inspection_run_id', sa.String(length=64), nullable=True),
        sa.Column('production_detection_result_id', sa.String(length=64), nullable=True),
        sa.Column('qualification_run_id', sa.String(length=64), nullable=True),
        sa.Column('qualification_report_id', sa.String(length=64), nullable=True),
        sa.Column('shadow_observation_id', sa.String(length=64), nullable=True),
        sa.Column('reported_by', sa.String(length=128), nullable=True),
        sa.Column('reported_role', sa.String(length=64), nullable=True),
        sa.Column('report_source', sa.String(length=64), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('evidence_refs_json', sa.JSON(), nullable=True),
        sa.Column('model_output_json', sa.JSON(), nullable=True),
        sa.Column('human_or_downstream_decision_json', sa.JSON(), nullable=True),
        sa.Column('affected_scope_json', sa.JSON(), nullable=True),
        sa.Column('confirmed_by', sa.String(length=128), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_quality_incidents_tenant_id', 'qc_quality_incidents', ['tenant_id'])
    op.create_index('ix_qc_quality_incidents_training_pack_id', 'qc_quality_incidents', ['training_pack_id'])
    op.create_index('ix_qc_quality_incidents_incident_type', 'qc_quality_incidents', ['incident_type'])
    op.create_index('ix_qc_quality_incidents_status', 'qc_quality_incidents', ['status'])

    op.create_table(
        'qc_scope_suspensions',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('incident_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=True),
        sa.Column('station_id', sa.String(length=64), nullable=True),
        sa.Column('detection_point_code', sa.String(length=64), nullable=True),
        sa.Column('provider', sa.String(length=128), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('scope_json', sa.JSON(), nullable=True),
        sa.Column('suspension_type', sa.String(length=48), nullable=False),
        sa.Column('status', sa.String(length=40), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('lifted_by', sa.String(length=128), nullable=True),
        sa.Column('lifted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lift_reason', sa.Text(), nullable=True),
        sa.Column('requalification_report_id', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['incident_id'], ['qc_quality_incidents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_scope_suspensions_tenant_id', 'qc_scope_suspensions', ['tenant_id'])
    op.create_index('ix_qc_scope_suspensions_incident_id', 'qc_scope_suspensions', ['incident_id'])
    op.create_index('ix_qc_scope_suspensions_training_pack_id', 'qc_scope_suspensions', ['training_pack_id'])
    op.create_index('ix_qc_scope_suspensions_status', 'qc_scope_suspensions', ['status'])

    op.create_table(
        'qc_requalification_requirements',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('incident_id', sa.String(length=64), nullable=False),
        sa.Column('suspension_id', sa.String(length=64), nullable=True),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=True),
        sa.Column('station_id', sa.String(length=64), nullable=True),
        sa.Column('detection_point_code', sa.String(length=64), nullable=True),
        sa.Column('previous_qualification_report_id', sa.String(length=64), nullable=True),
        sa.Column('required_reason', sa.Text(), nullable=True),
        sa.Column('required_scope_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('satisfied_by_report_id', sa.String(length=64), nullable=True),
        sa.Column('satisfied_by', sa.String(length=128), nullable=True),
        sa.Column('satisfied_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['incident_id'], ['qc_quality_incidents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_requalification_requirements_tenant_id', 'qc_requalification_requirements', ['tenant_id'])
    op.create_index('ix_qc_requalification_requirements_incident_id', 'qc_requalification_requirements', ['incident_id'])
    op.create_index('ix_qc_requalification_requirements_training_pack_id', 'qc_requalification_requirements', ['training_pack_id'])
    op.create_index('ix_qc_requalification_requirements_status', 'qc_requalification_requirements', ['status'])

    op.create_table(
        'qc_incident_audit_events',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('incident_id', sa.String(length=64), nullable=True),
        sa.Column('suspension_id', sa.String(length=64), nullable=True),
        sa.Column('requalification_requirement_id', sa.String(length=64), nullable=True),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('actor_id', sa.String(length=128), nullable=True),
        sa.Column('actor_role', sa.String(length=64), nullable=True),
        sa.Column('event_payload_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_incident_audit_events_tenant_id', 'qc_incident_audit_events', ['tenant_id'])
    op.create_index('ix_qc_incident_audit_events_incident_id', 'qc_incident_audit_events', ['incident_id'])
    op.create_index('ix_qc_incident_audit_events_event_type', 'qc_incident_audit_events', ['event_type'])


def downgrade() -> None:
    op.drop_table('qc_incident_audit_events')
    op.drop_table('qc_requalification_requirements')
    op.drop_table('qc_scope_suspensions')
    op.drop_table('qc_quality_incidents')
