"""detection point region annotations (PRD Authoring Extension §2)

Adds ``regions_json`` to ``qc_detection_points`` — a JSON list of normalized
bounding boxes ``[{image_id, x, y, w, h}]`` (0–1 coords, top-left origin) that
spatially ground a detection point on the SKU's standard photos.

Revision ID: 020
Revises: 019
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = '020'
down_revision = '019'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'qc_detection_points',
        sa.Column('regions_json', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('qc_detection_points', 'regions_json')
