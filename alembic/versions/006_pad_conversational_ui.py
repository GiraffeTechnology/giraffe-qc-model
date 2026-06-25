"""pad conversational ui tables

Revision ID: 006
Revises: 005
Create Date: 2026-06-25
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'qc_operator_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('username', sa.String(length=128), nullable=False),
        sa.Column('display_name', sa.String(length=256), nullable=True),
        sa.Column('role', sa.String(length=64), nullable=False, server_default='operator'),
        sa.Column('preferred_language', sa.String(length=16), nullable=False, server_default='en'),
        sa.Column('password_hash', sa.String(length=512), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('tenant_id', 'username', name='uq_operator_tenant_username'),
    )
    op.create_table(
        'qc_conversation_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=False),
        sa.Column('preferred_language', sa.String(length=16), nullable=False, server_default='en'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['operator_id'], ['qc_operator_profiles.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'qc_conversation_messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.String(length=64), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('operator_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False),
        sa.Column('source_language', sa.String(length=16), nullable=True),
        sa.Column('preferred_language', sa.String(length=16), nullable=True),
        sa.Column('raw_text_original', sa.Text(), nullable=True),
        sa.Column('normalized_text_en', sa.Text(), nullable=True),
        sa.Column('translated_output_text', sa.Text(), nullable=True),
        sa.Column('intent', sa.String(length=64), nullable=True),
        sa.Column('confidence_score', sa.Float(), nullable=True),
        sa.Column('action_json', sa.Text(), nullable=True),
        sa.Column('linked_intake_id', sa.Integer(), nullable=True),
        sa.Column('linked_job_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.ForeignKeyConstraint(['operator_id'], ['qc_operator_profiles.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['qc_conversation_sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('qc_conversation_messages')
    op.drop_table('qc_conversation_sessions')
    op.drop_table('qc_operator_profiles')
