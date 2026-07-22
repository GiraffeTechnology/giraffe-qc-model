"""checkpoint result review provenance (operator vs model)

The preset Stage 2 workflow requires operator review of every checkpoint
before a job may finalize as pass. Record where each checkpoint result came
from so finalize can enforce it.

Revision ID: 026
Revises: 025
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "qc_checkpoint_results",
        sa.Column(
            "review_source",
            sa.String(length=16),
            nullable=False,
            server_default="model",
        ),
    )
    op.add_column(
        "qc_checkpoint_results",
        sa.Column("reviewed_by", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("qc_checkpoint_results", "reviewed_by")
    op.drop_column("qc_checkpoint_results", "review_source")
