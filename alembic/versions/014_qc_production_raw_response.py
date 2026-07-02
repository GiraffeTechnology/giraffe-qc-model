"""qc production raw provider response (PR 26)

Revision ID: 014
Revises: 013
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'qc_production_detection_results',
        sa.Column('raw_provider_response_json', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('qc_production_detection_results', 'raw_provider_response_json')
