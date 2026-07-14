"""detection point expected features and CV configuration

Revision ID: 023
Revises: 022
Create Date: 2026-07-14
"""
from alembic import op
import sqlalchemy as sa

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("qc_detection_points") as batch:
        batch.add_column(sa.Column("expected_features_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("cv_config_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("qc_detection_points") as batch:
        batch.drop_column("cv_config_json")
        batch.drop_column("expected_features_json")
