"""Read models for the configuration / training UI.

Computes the "trained" status for a SKU and gathers dashboard/revision data.
A SKU is considered *trained* only when all three configuration inputs exist:

* at least one standard photo,
* an active standard revision,
* at least one active detection point on that revision.

This is the same gate the production-line Pad task list relies on.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from src.db.intake_models import QCStandardIntake
from src.db.sku_models import (
    QCDetectionPoint,
    QCSkuItem,
    QCSkuStandardRevision,
    QCStandardPhoto,
)


@dataclass
class TrainingStatus:
    sku_id: str
    item_number: str
    name: str
    has_photos: bool
    photo_count: int
    has_active_revision: bool
    active_revision_no: Optional[int]
    detection_point_count: int
    last_revision_at: Optional[datetime]
    trained: bool


def _active_revision(
    db: Session, sku_id: str, tenant_id: str
) -> Optional[QCSkuStandardRevision]:
    return (
        db.query(QCSkuStandardRevision)
        .filter_by(sku_id=sku_id, tenant_id=tenant_id, status="active")
        .order_by(QCSkuStandardRevision.revision_no.desc())
        .first()
    )


def compute_training_status(db: Session, sku: QCSkuItem) -> TrainingStatus:
    tenant_id = sku.tenant_id
    photo_count = (
        db.query(QCStandardPhoto)
        .filter_by(sku_id=sku.id, tenant_id=tenant_id)
        .count()
    )
    active = _active_revision(db, sku.id, tenant_id)
    dp_count = 0
    last_revision_at: Optional[datetime] = None
    if active is not None:
        dp_count = (
            db.query(QCDetectionPoint)
            .filter_by(
                standard_revision_id=active.id,
                tenant_id=tenant_id,
                is_active=True,
            )
            .count()
        )
        last_revision_at = active.confirmed_at or active.created_at

    has_photos = photo_count > 0
    has_active = active is not None
    trained = has_photos and has_active and dp_count >= 1
    return TrainingStatus(
        sku_id=sku.id,
        item_number=sku.item_number,
        name=sku.name,
        has_photos=has_photos,
        photo_count=photo_count,
        has_active_revision=has_active,
        active_revision_no=active.revision_no if active else None,
        detection_point_count=dp_count,
        last_revision_at=last_revision_at,
        trained=trained,
    )


def list_training_dashboard(db: Session, tenant_id: str) -> List[TrainingStatus]:
    skus = (
        db.query(QCSkuItem)
        .filter_by(tenant_id=tenant_id, status="active")
        .order_by(QCSkuItem.created_at.desc())
        .all()
    )
    return [compute_training_status(db, sku) for sku in skus]


def list_intakes(db: Session, sku_id: str, tenant_id: str) -> List[QCStandardIntake]:
    return (
        db.query(QCStandardIntake)
        .filter_by(sku_id=sku_id, tenant_id=tenant_id)
        .order_by(QCStandardIntake.created_at.desc())
        .all()
    )


def list_revisions(
    db: Session, sku_id: str, tenant_id: str
) -> List[QCSkuStandardRevision]:
    return (
        db.query(QCSkuStandardRevision)
        .filter_by(sku_id=sku_id, tenant_id=tenant_id)
        .order_by(QCSkuStandardRevision.revision_no.desc())
        .all()
    )


def candidate_checkpoints(intake: QCStandardIntake) -> List[dict]:
    """Return the extracted candidate checkpoints for editing, if any."""
    payload = intake.extracted_json or {}
    checkpoints = payload.get("checkpoints") or []
    return [dict(cp) for cp in checkpoints]
