"""Hot-pluggable Edge CV subsystem: devices, sessions, models, jobs, results,
metrics, and live-capture photos.

Revision ID: 018
Revises: 017
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = '018'
down_revision = '017'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'edge_cv_devices',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('device_name', sa.String(256), nullable=False),
        sa.Column('device_type', sa.String(64), nullable=False),
        sa.Column('serial_number', sa.String(256)),
        sa.Column('mac_address', sa.String(64)),
        sa.Column('ip_address', sa.String(64)),
        sa.Column('agent_version', sa.String(64)),
        sa.Column('status', sa.String(32), nullable=False, server_default='unknown'),
        sa.Column('capabilities_json', sa.JSON()),
        sa.Column('max_concurrent_jobs', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('current_active_jobs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True)),
        sa.Column('last_seen_at', sa.DateTime(timezone=True)),
        sa.Column('is_enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('tenant_id', 'device_name', name='uq_edge_cv_device_name'),
    )
    op.create_index('idx_edge_cv_devices_status', 'edge_cv_devices', ['status'])
    op.create_index('idx_edge_cv_devices_device_type', 'edge_cv_devices', ['device_type'])
    op.create_index('idx_edge_cv_devices_last_heartbeat_at', 'edge_cv_devices', ['last_heartbeat_at'])
    op.create_index('idx_edge_cv_devices_is_enabled', 'edge_cv_devices', ['is_enabled'])
    op.create_index('idx_edge_cv_devices_tenant_id', 'edge_cv_devices', ['tenant_id'])

    op.create_table(
        'edge_cv_device_sessions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('device_id', sa.String(64), sa.ForeignKey('edge_cv_devices.id'), nullable=False),
        sa.Column('session_id', sa.String(64), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('ended_at', sa.DateTime(timezone=True)),
        sa.Column('status', sa.String(32), nullable=False, server_default='active'),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True)),
        sa.Column('disconnect_reason', sa.String(128)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('session_id', name='uq_edge_cv_session_id'),
    )
    op.create_index('idx_edge_cv_sessions_device_id', 'edge_cv_device_sessions', ['device_id'])
    op.create_index('idx_edge_cv_sessions_session_id', 'edge_cv_device_sessions', ['session_id'])
    op.create_index('idx_edge_cv_sessions_status', 'edge_cv_device_sessions', ['status'])

    op.create_table(
        'edge_cv_models',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('model_name', sa.String(256), nullable=False),
        sa.Column('model_version', sa.String(64), nullable=False, server_default='0.1.0'),
        sa.Column('task_type', sa.String(64), nullable=False),
        sa.Column('model_format', sa.String(32), nullable=False, server_default='mock'),
        sa.Column('artifact_uri', sa.String(512)),
        sa.Column('input_width', sa.Integer()),
        sa.Column('input_height', sa.Integer()),
        sa.Column('precision', sa.String(32)),
        sa.Column('target_device_type', sa.String(64), nullable=False, server_default='any'),
        sa.Column('required_capabilities_json', sa.JSON()),
        sa.Column('min_memory_mb', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('model_hash', sa.String(128)),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('idx_edge_cv_models_task_type', 'edge_cv_models', ['task_type'])
    op.create_index('idx_edge_cv_models_is_active', 'edge_cv_models', ['is_active'])
    op.create_index('idx_edge_cv_models_tenant_id', 'edge_cv_models', ['tenant_id'])

    op.create_table(
        'cv_jobs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('source_asset_id', sa.String(128)),
        sa.Column('inspection_id', sa.String(128)),
        sa.Column('requested_by', sa.String(128)),
        sa.Column('task_type', sa.String(64), nullable=False),
        sa.Column('priority', sa.String(16), nullable=False, server_default='normal'),
        sa.Column('status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('assigned_device_id', sa.String(64)),
        sa.Column('assigned_session_id', sa.String(64)),
        sa.Column('model_id', sa.String(64)),
        sa.Column('input_payload_json', sa.JSON()),
        sa.Column('lease_owner_device_id', sa.String(64)),
        sa.Column('lease_owner_session_id', sa.String(64)),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True)),
        sa.Column('retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_retries', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('error_code', sa.String(64)),
        sa.Column('error_message', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('queued_at', sa.DateTime(timezone=True)),
        sa.Column('leased_at', sa.DateTime(timezone=True)),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.Column('cancelled_at', sa.DateTime(timezone=True)),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('idx_cv_jobs_status', 'cv_jobs', ['status'])
    op.create_index('idx_cv_jobs_task_type', 'cv_jobs', ['task_type'])
    op.create_index('idx_cv_jobs_priority', 'cv_jobs', ['priority'])
    op.create_index('idx_cv_jobs_assigned_device_id', 'cv_jobs', ['assigned_device_id'])
    op.create_index('idx_cv_jobs_lease_expires_at', 'cv_jobs', ['lease_expires_at'])
    op.create_index('idx_cv_jobs_inspection_id', 'cv_jobs', ['inspection_id'])
    op.create_index('idx_cv_jobs_source_asset_id', 'cv_jobs', ['source_asset_id'])
    op.create_index('idx_cv_jobs_tenant_id', 'cv_jobs', ['tenant_id'])

    op.create_table(
        'cv_job_events',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('cv_job_id', sa.String(64), sa.ForeignKey('cv_jobs.id'), nullable=False),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('from_status', sa.String(32)),
        sa.Column('to_status', sa.String(32)),
        sa.Column('event_type', sa.String(64), nullable=False),
        sa.Column('event_payload_json', sa.JSON()),
        sa.Column('created_by', sa.String(128)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('idx_cv_job_events_cv_job_id', 'cv_job_events', ['cv_job_id'])
    op.create_index('idx_cv_job_events_tenant_id', 'cv_job_events', ['tenant_id'])

    op.create_table(
        'cv_results',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('cv_job_id', sa.String(64), sa.ForeignKey('cv_jobs.id'), nullable=False),
        sa.Column('device_id', sa.String(64)),
        sa.Column('session_id', sa.String(64)),
        sa.Column('model_id', sa.String(64)),
        sa.Column('result_type', sa.String(64), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('pass_fail_hint', sa.String(32), nullable=False, server_default='unknown'),
        sa.Column('detections_json', sa.JSON()),
        sa.Column('measurements_json', sa.JSON()),
        sa.Column('features_json', sa.JSON()),
        sa.Column('raw_output_json', sa.JSON()),
        sa.Column('result_hash', sa.String(128)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.UniqueConstraint('cv_job_id', 'device_id', 'session_id', name='uq_cv_result_job_device_session'),
    )
    op.create_index('idx_cv_results_cv_job_id', 'cv_results', ['cv_job_id'])
    op.create_index('idx_cv_results_device_id', 'cv_results', ['device_id'])
    op.create_index('idx_cv_results_tenant_id', 'cv_results', ['tenant_id'])

    op.create_table(
        'cv_result_assets',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('cv_result_id', sa.String(64), sa.ForeignKey('cv_results.id'), nullable=False),
        sa.Column('asset_type', sa.String(64), nullable=False),
        sa.Column('asset_uri', sa.String(512), nullable=False),
        sa.Column('asset_hash', sa.String(128)),
        sa.Column('width', sa.Integer()),
        sa.Column('height', sa.Integer()),
        sa.Column('metadata_json', sa.JSON()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('idx_cv_result_assets_cv_result_id', 'cv_result_assets', ['cv_result_id'])

    op.create_table(
        'edge_cv_device_metrics',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('device_id', sa.String(64), nullable=False),
        sa.Column('session_id', sa.String(64)),
        sa.Column('cpu_usage_percent', sa.Float()),
        sa.Column('gpu_usage_percent', sa.Float()),
        sa.Column('memory_used_mb', sa.Float()),
        sa.Column('memory_total_mb', sa.Float()),
        sa.Column('temperature_celsius', sa.Float()),
        sa.Column('power_mode', sa.String(32)),
        sa.Column('disk_used_percent', sa.Float()),
        sa.Column('active_job_count', sa.Integer()),
        sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('idx_edge_cv_metrics_device_id', 'edge_cv_device_metrics', ['device_id'])
    op.create_index('idx_edge_cv_metrics_recorded_at', 'edge_cv_device_metrics', ['recorded_at'])

    # Live-Capture Auto-Lock addendum.
    op.create_table(
        'cv_captured_photos',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('tenant_id', sa.String(64), nullable=False, server_default='default'),
        sa.Column('device_id', sa.String(64), nullable=False),
        sa.Column('session_id', sa.String(64)),
        sa.Column('captured_by_user_id', sa.String(128)),
        sa.Column('trigger_type', sa.String(32), nullable=False, server_default='live_auto_lock'),
        sa.Column('candidate_confidence', sa.Float()),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('capture_time_label', sa.String(32)),
        sa.Column('gps_lat', sa.Float()),
        sa.Column('gps_lon', sa.Float()),
        sa.Column('gps_accuracy_m', sa.Float()),
        sa.Column('image_uri', sa.String(512), nullable=False),
        sa.Column('image_hash', sa.String(128)),
        sa.Column('width', sa.Integer()),
        sa.Column('height', sa.Integer()),
        sa.Column('linked_cv_job_id', sa.String(64)),
        sa.Column('qc_model_dispatch_status', sa.String(32), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )
    op.create_index('idx_captured_photos_device_id', 'cv_captured_photos', ['device_id'])
    op.create_index('idx_captured_photos_captured_at', 'cv_captured_photos', ['captured_at'])
    op.create_index('idx_captured_photos_user_id', 'cv_captured_photos', ['captured_by_user_id'])
    op.create_index('idx_captured_photos_linked_cv_job_id', 'cv_captured_photos', ['linked_cv_job_id'])


def downgrade() -> None:
    op.drop_table('cv_captured_photos')
    op.drop_index('idx_edge_cv_metrics_recorded_at', table_name='edge_cv_device_metrics')
    op.drop_index('idx_edge_cv_metrics_device_id', table_name='edge_cv_device_metrics')
    op.drop_table('edge_cv_device_metrics')
    op.drop_table('cv_result_assets')
    op.drop_table('cv_results')
    op.drop_table('cv_job_events')
    op.drop_table('cv_jobs')
    op.drop_table('edge_cv_models')
    op.drop_table('edge_cv_device_sessions')
    op.drop_table('edge_cv_devices')
