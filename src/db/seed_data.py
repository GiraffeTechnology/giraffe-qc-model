"""Seed data for QC SKU catalog — used in tests and initial deployment."""
import uuid
from datetime import timezone
from datetime import datetime

from sqlalchemy.orm import Session

from src.db.sku_models import (
    QCSkuItem,
    QCSkuStandardRevision,
    QCDetectionPoint,
)


def _uid() -> str:
    return uuid.uuid4().hex


def seed_flower_brooch(db: Session, tenant_id: str = "default") -> QCSkuItem:
    """Seed FLOWER-BROOCH-001 with an active standard revision and 4 checkpoints.

    Idempotent: returns existing SKU if already present.
    """
    existing = (
        db.query(QCSkuItem)
        .filter_by(tenant_id=tenant_id, item_number="FLOWER-BROOCH-001")
        .first()
    )
    if existing is not None:
        return existing

    sku = QCSkuItem(
        id=_uid(),
        tenant_id=tenant_id,
        item_number="FLOWER-BROOCH-001",
        name="Flower Brooch",
        category="Jewelry",
        description="Hand-crafted flower brooch with pearl center and rhinestone petals.",
        status="active",
    )
    db.add(sku)
    db.flush()

    revision = QCSkuStandardRevision(
        id=_uid(),
        sku_id=sku.id,
        tenant_id=tenant_id,
        revision_no=1,
        status="active",
        created_from="seed",
        confirmed_by="system",
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(revision)
    db.flush()

    checkpoints = [
        QCDetectionPoint(
            id=_uid(),
            tenant_id=tenant_id,
            sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="STAMEN_CENTERING",
            label="Stamen Centering",
            description="Central stamen must be aligned within 2mm of geometric center.",
            severity="major",
            sort_order=1,
            is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(),
            tenant_id=tenant_id,
            sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="PEARL_COUNT",
            label="Pearl Count",
            description="Exactly 3 pearls must be present around the stamen.",
            expected_value="3",
            severity="critical",
            sort_order=2,
            is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(),
            tenant_id=tenant_id,
            sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="RHINESTONE_COUNT",
            label="Rhinestone Count",
            description="Exactly 8 rhinestones must be set in the outer petal ring.",
            expected_value="8",
            severity="critical",
            sort_order=3,
            is_active=True,
        ),
        QCDetectionPoint(
            id=_uid(),
            tenant_id=tenant_id,
            sku_id=sku.id,
            standard_revision_id=revision.id,
            point_code="PETAL_INTEGRITY",
            label="Petal Integrity",
            description="No petals may be bent, cracked, or missing.",
            severity="critical",
            sort_order=4,
            is_active=True,
        ),
    ]
    for cp in checkpoints:
        db.add(cp)

    db.commit()
    db.refresh(sku)
    return sku
