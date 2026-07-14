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
    op.add_column("qc_detection_points", sa.Column("expected_features_json", sa.JSON(), nullable=True))
    op.add_column("qc_detection_points", sa.Column("cv_config_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("qc_detection_points", "cv_config_json")
    op.drop_column("qc_detection_points", "expected_features_json")
