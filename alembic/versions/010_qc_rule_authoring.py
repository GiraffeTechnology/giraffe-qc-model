"""qc llm rule authoring (PR 22)

Revision ID: 010
Revises: 009
Create Date: 2026-07-01

Reuses the PR 20 proposal table for authored proposals: makes learning_job_id
nullable and adds authoring/fragment traceability columns. Adds the
qc_rule_authoring_jobs table.
"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009'
branch_labels = None
depends_on = None

_PROPOSALS = 'qc_learned_detection_point_proposals'


def upgrade() -> None:
    # Extend the PR 20 proposal table (reused, not duplicated). batch_alter is
    # required so SQLite can change the learning_job_id nullability.
    with op.batch_alter_table(_PROPOSALS) as batch:
        batch.alter_column('learning_job_id', existing_type=sa.String(length=64), nullable=True)
        batch.add_column(sa.Column('rule_authoring_job_id', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('source_fragment_id', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('evidence_required_json', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('guard_override_note', sa.Text(), nullable=True))
    op.create_index('ix_qc_learned_dp_proposals_authoring_job', _PROPOSALS, ['rule_authoring_job_id'])
    op.create_index('ix_qc_learned_dp_proposals_source_fragment', _PROPOSALS, ['source_fragment_id'])

    op.create_table(
        'qc_rule_authoring_jobs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('source_id', sa.String(length=64), nullable=True),
        sa.Column('source_fragment_id', sa.String(length=64), nullable=True),
        sa.Column('extraction_job_id', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('provider', sa.String(length=128), nullable=True),
        sa.Column('model', sa.String(length=128), nullable=True),
        sa.Column('proposal_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_rule_authoring_jobs_tenant_id', 'qc_rule_authoring_jobs', ['tenant_id'])
    op.create_index('ix_qc_rule_authoring_jobs_training_pack_id', 'qc_rule_authoring_jobs', ['training_pack_id'])
    op.create_index('ix_qc_rule_authoring_jobs_source_fragment_id', 'qc_rule_authoring_jobs', ['source_fragment_id'])
    op.create_index('ix_qc_rule_authoring_jobs_extraction_job_id', 'qc_rule_authoring_jobs', ['extraction_job_id'])


def downgrade() -> None:
    op.drop_table('qc_rule_authoring_jobs')
    op.drop_index('ix_qc_learned_dp_proposals_source_fragment', table_name=_PROPOSALS)
    op.drop_index('ix_qc_learned_dp_proposals_authoring_job', table_name=_PROPOSALS)
    with op.batch_alter_table(_PROPOSALS) as batch:
        batch.drop_column('guard_override_note')
        batch.drop_column('evidence_required_json')
        batch.drop_column('source_fragment_id')
        batch.drop_column('rule_authoring_job_id')
        batch.alter_column('learning_job_id', existing_type=sa.String(length=64), nullable=False)
