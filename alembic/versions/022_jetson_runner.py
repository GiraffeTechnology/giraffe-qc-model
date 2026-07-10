"""Jetson Xavier NX inference runner: provisioned runners + pairing audit.

Revision ID: 022
Revises: 021
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = '022'
down_revision = '021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_jetson_runners',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('jetson_device_id', sa.String(128), nullable=False),
        sa.Column('pubkey_fingerprint', sa.String(64), nullable=False),
        sa.Column('agent_version', sa.String(64)),
        sa.Column('provisioned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('pairing_status', sa.String(32), nullable=False, server_default='unpaired'),
        sa.Column('pairing_path', sa.String(16)),
        sa.Column('workstation_pk', sa.String(64), sa.ForeignKey('qc_workstations.id')),
        sa.Column('paired_pad_device_id', sa.String(128)),
        sa.Column('paired_at', sa.DateTime(timezone=True)),
        sa.Column('unpaired_at', sa.DateTime(timezone=True)),
        sa.Column('readiness_state', sa.String(32)),
        sa.Column('service_up', sa.Boolean()),
        sa.Column('model_loaded', sa.Boolean()),
        sa.Column('temperature_c', sa.Float()),
        sa.Column('throttling', sa.Boolean()),
        sa.Column('disk_free_percent', sa.Float()),
        sa.Column('last_inference_latency_ms', sa.Integer()),
        sa.Column('last_seen_at', sa.DateTime(timezone=True)),
        sa.Column('health_reported_at', sa.DateTime(timezone=True)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('tenant_id', 'jetson_device_id', name='uq_jetson_device_id'),
    )
    op.create_index('idx_jetson_runners_tenant_id', 'qc_jetson_runners', ['tenant_id'])
    op.create_index('idx_jetson_runners_device_id', 'qc_jetson_runners', ['jetson_device_id'])
    op.create_index('idx_jetson_runners_pairing_status', 'qc_jetson_runners', ['pairing_status'])
    op.create_index('idx_jetson_runners_workstation_pk', 'qc_jetson_runners', ['workstation_pk'])
    op.create_index('idx_jetson_runners_pad_device_id', 'qc_jetson_runners', ['paired_pad_device_id'])

    op.create_table(
        'qc_jetson_pairing_events',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('runner_pk', sa.String(64), sa.ForeignKey('qc_jetson_runners.id'), nullable=False),
        sa.Column('event_type', sa.String(32), nullable=False),
        sa.Column('pairing_path', sa.String(16)),
        sa.Column('workstation_id', sa.String(128)),
        sa.Column('pad_device_id', sa.String(128)),
        sa.Column('detail_json', sa.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('idx_jetson_events_runner_pk', 'qc_jetson_pairing_events', ['runner_pk'])
    op.create_index('idx_jetson_events_tenant_id', 'qc_jetson_pairing_events', ['tenant_id'])


def downgrade() -> None:
    op.drop_table('qc_jetson_pairing_events')
    op.drop_table('qc_jetson_runners')
