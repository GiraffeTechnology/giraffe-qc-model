"""digital QC studio training judgments (PRD workflow §9.5-9.8)

Creates ``qc_training_judgments``: one row per CV+4B judgment against a
labeled sample, carrying the administrator's per-decision review. The
rolling 29/30-window publish gate
(``src.qc_model.qualification.training_gate``) is computed from reviewed
rows in this table.

Revision ID: 027
Revises: 026
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa


revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "qc_training_judgments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("sku_id", sa.String(length=64), nullable=False),
        sa.Column("standard_revision_id", sa.String(length=64), nullable=False),
        sa.Column("sample_image_path", sa.String(length=512), nullable=True),
        sa.Column("ground_truth_label", sa.String(length=32), nullable=False),
        sa.Column("ground_truth_notes", sa.Text(), nullable=True),
        sa.Column("cv_evidence_json", sa.JSON(), nullable=True),
        sa.Column("model_provider", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("model_elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("model_overall_result", sa.String(length=16), nullable=False),
        sa.Column("model_checkpoint_results_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="awaiting_admin_review"),
        sa.Column("admin_decision", sa.String(length=16), nullable=True),
        sa.Column("admin_id", sa.String(length=128), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correction_json", sa.JSON(), nullable=True),
        sa.Column("is_false_pass", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["sku_id"], ["qc_sku_items.id"]),
        sa.ForeignKeyConstraint(["standard_revision_id"], ["qc_sku_standard_revisions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_qc_training_judgments_tenant_id", "qc_training_judgments", ["tenant_id"])
    op.create_index("ix_qc_training_judgments_sku_id", "qc_training_judgments", ["sku_id"])
    op.create_index(
        "ix_qc_training_judgments_standard_revision_id", "qc_training_judgments", ["standard_revision_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_qc_training_judgments_standard_revision_id", table_name="qc_training_judgments")
    op.drop_index("ix_qc_training_judgments_sku_id", table_name="qc_training_judgments")
    op.drop_index("ix_qc_training_judgments_tenant_id", table_name="qc_training_judgments")
    op.drop_table("qc_training_judgments")
