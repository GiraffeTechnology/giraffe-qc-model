"""append-only authenticated probation transition audit

Revision ID: 025
Revises: 024
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa


revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qc_probation_transition_audits",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("probation_id", sa.String(length=64), nullable=False),
        sa.Column("standard_revision_id", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("previous_status", sa.String(length=32), nullable=False),
        sa.Column("new_status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(["probation_id"], ["qc_probations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_qc_probation_transition_audits_tenant_id",
        "qc_probation_transition_audits",
        ["tenant_id"],
    )
    op.create_index(
        "ix_qc_probation_transition_audits_probation_id",
        "qc_probation_transition_audits",
        ["probation_id"],
    )
    op.create_index(
        "ix_qc_probation_transition_audits_standard_revision_id",
        "qc_probation_transition_audits",
        ["standard_revision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_qc_probation_transition_audits_standard_revision_id",
        table_name="qc_probation_transition_audits",
    )
    op.drop_index(
        "ix_qc_probation_transition_audits_probation_id",
        table_name="qc_probation_transition_audits",
    )
    op.drop_index(
        "ix_qc_probation_transition_audits_tenant_id",
        table_name="qc_probation_transition_audits",
    )
    op.drop_table("qc_probation_transition_audits")
