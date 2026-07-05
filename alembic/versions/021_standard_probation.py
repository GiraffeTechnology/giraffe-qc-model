"""standard probation / qualification workflow (PRD Authoring Extension §3)

Creates ``qc_probations`` (one probation record per standard revision, with the
running counters + qualification thresholds) and ``qc_probation_jobs`` (one row
per real production job worked while a standard is on probation, recording the
AI/human verdict pair and per-detection-point disagreements).

Revision ID: 021
Revises: 020
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = '021'
down_revision = '020'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_probations',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=True),
        sa.Column('standard_revision_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='active'),
        sa.Column('min_sample_size', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('agreement_threshold', sa.Float(), nullable=False, server_default='0.9'),
        sa.Column('recheck_interval', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('jobs_recorded', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('agreements', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('qualified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paused_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'standard_revision_id', name='uq_probation_tenant_revision'),
    )
    op.create_index('ix_qc_probations_tenant_id', 'qc_probations', ['tenant_id'])
    op.create_index('ix_qc_probations_sku_id', 'qc_probations', ['sku_id'])
    op.create_index('ix_qc_probations_standard_revision_id', 'qc_probations', ['standard_revision_id'])

    op.create_table(
        'qc_probation_jobs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('probation_id', sa.String(length=64), nullable=False),
        sa.Column('standard_revision_id', sa.String(length=64), nullable=False),
        sa.Column('job_ref', sa.String(length=128), nullable=True),
        sa.Column('ai_verdict', sa.String(length=32), nullable=False),
        sa.Column('human_final_verdict', sa.String(length=32), nullable=False),
        sa.Column('agreed', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('point_disagreements_json', sa.JSON(), nullable=True),
        sa.Column('sequence_no', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['probation_id'], ['qc_probations.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'probation_id', 'job_ref', name='uq_probation_job_ref'),
    )
    op.create_index('ix_qc_probation_jobs_tenant_id', 'qc_probation_jobs', ['tenant_id'])
    op.create_index('ix_qc_probation_jobs_probation_id', 'qc_probation_jobs', ['probation_id'])
    op.create_index('ix_qc_probation_jobs_standard_revision_id', 'qc_probation_jobs', ['standard_revision_id'])


def downgrade() -> None:
    op.drop_index('ix_qc_probation_jobs_standard_revision_id', table_name='qc_probation_jobs')
    op.drop_index('ix_qc_probation_jobs_probation_id', table_name='qc_probation_jobs')
    op.drop_index('ix_qc_probation_jobs_tenant_id', table_name='qc_probation_jobs')
    op.drop_table('qc_probation_jobs')
    op.drop_index('ix_qc_probations_standard_revision_id', table_name='qc_probations')
    op.drop_index('ix_qc_probations_sku_id', table_name='qc_probations')
    op.drop_index('ix_qc_probations_tenant_id', table_name='qc_probations')
    op.drop_table('qc_probations')
