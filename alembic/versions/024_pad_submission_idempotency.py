"""tenant-scoped idempotency for Pad S4 submissions

Revision ID: 024
Revises: 023
Create Date: 2026-07-14
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("qc_pad_submissions") as batch:
        batch.create_unique_constraint("uq_pad_submission_tenant_job", ["tenant_id", "job_ref"])


def downgrade() -> None:
    with op.batch_alter_table("qc_pad_submissions") as batch:
        batch.drop_constraint("uq_pad_submission_tenant_job", type_="unique")
