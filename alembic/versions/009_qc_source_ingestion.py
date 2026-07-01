"""qc source ingestion workbench tables (PR 21)

Revision ID: 009
Revises: 008
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_source_documents',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('sku_id', sa.String(length=64), nullable=True),
        sa.Column('source_type', sa.String(length=48), nullable=False),
        sa.Column('title', sa.String(length=256), nullable=True),
        sa.Column('text_content', sa.Text(), nullable=True),
        sa.Column('file_ref', sa.String(length=1024), nullable=True),
        sa.Column('mime_type', sa.String(length=128), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='draft'),
        sa.Column('created_by', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_source_documents_tenant_id', 'qc_source_documents', ['tenant_id'])
    op.create_index('ix_qc_source_documents_training_pack_id', 'qc_source_documents', ['training_pack_id'])
    op.create_index('ix_qc_source_documents_sku_id', 'qc_source_documents', ['sku_id'])

    op.create_table(
        'qc_source_extraction_jobs',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('source_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='pending'),
        sa.Column('provider', sa.String(length=128), nullable=True),
        sa.Column('fragment_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['source_id'], ['qc_source_documents.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_source_extraction_jobs_tenant_id', 'qc_source_extraction_jobs', ['tenant_id'])
    op.create_index('ix_qc_source_extraction_jobs_source_id', 'qc_source_extraction_jobs', ['source_id'])
    op.create_index('ix_qc_source_extraction_jobs_training_pack_id', 'qc_source_extraction_jobs', ['training_pack_id'])

    op.create_table(
        'qc_source_fragments',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('source_id', sa.String(length=64), nullable=False),
        sa.Column('extraction_job_id', sa.String(length=64), nullable=False),
        sa.Column('training_pack_id', sa.String(length=64), nullable=False),
        sa.Column('fragment_type', sa.String(length=48), nullable=False),
        sa.Column('candidate_label', sa.String(length=32), nullable=False, server_default='review'),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('source_excerpt', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='draft'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['source_id'], ['qc_source_documents.id']),
        sa.ForeignKeyConstraint(['extraction_job_id'], ['qc_source_extraction_jobs.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_qc_source_fragments_tenant_id', 'qc_source_fragments', ['tenant_id'])
    op.create_index('ix_qc_source_fragments_source_id', 'qc_source_fragments', ['source_id'])
    op.create_index('ix_qc_source_fragments_extraction_job_id', 'qc_source_fragments', ['extraction_job_id'])

    for table in ('qc_requirement_drafts', 'qc_boundary_drafts'):
        text_col = 'draft_text' if table == 'qc_requirement_drafts' else 'boundary_text'
        cols = [
            sa.Column('id', sa.String(length=64), nullable=False),
            sa.Column('tenant_id', sa.String(length=64), nullable=False),
            sa.Column('training_pack_id', sa.String(length=64), nullable=False),
            sa.Column('source_id', sa.String(length=64), nullable=False),
            sa.Column('extraction_job_id', sa.String(length=64), nullable=False),
            sa.Column('fragment_id', sa.String(length=64), nullable=False),
            sa.Column(text_col, sa.Text(), nullable=False),
            sa.Column('status', sa.String(length=32), nullable=False, server_default='draft'),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        ]
        if table == 'qc_requirement_drafts':
            cols.insert(7, sa.Column('proposed_checkpoint_category', sa.String(length=48), nullable=True))
        else:
            cols.insert(7, sa.Column('boundary_kind', sa.String(length=48), nullable=True))
        op.create_table(
            table,
            *cols,
            sa.ForeignKeyConstraint(['source_id'], ['qc_source_documents.id']),
            sa.ForeignKeyConstraint(['extraction_job_id'], ['qc_source_extraction_jobs.id']),
            sa.ForeignKeyConstraint(['fragment_id'], ['qc_source_fragments.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(f'ix_{table}_tenant_id', table, ['tenant_id'])
        op.create_index(f'ix_{table}_training_pack_id', table, ['training_pack_id'])
        op.create_index(f'ix_{table}_fragment_id', table, ['fragment_id'])


def downgrade() -> None:
    op.drop_table('qc_boundary_drafts')
    op.drop_table('qc_requirement_drafts')
    op.drop_table('qc_source_fragments')
    op.drop_table('qc_source_extraction_jobs')
    op.drop_table('qc_source_documents')
