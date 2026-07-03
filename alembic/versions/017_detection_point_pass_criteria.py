"""Add pass_criteria column to qc_detection_points.

Preserves the operator-confirmed pass criteria on each detection point so a
counting / tolerance rule (e.g. "pearl count 3") survives extract → review/edit
→ confirm without losing its criteria (Codex PR #31 P1).

Revision ID: 017
Revises: 016
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = '017'
down_revision = '016'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('qc_detection_points') as batch_op:
        batch_op.add_column(sa.Column('pass_criteria', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('qc_detection_points') as batch_op:
        batch_op.drop_column('pass_criteria')
