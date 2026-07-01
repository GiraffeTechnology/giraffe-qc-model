"""Checkpoint-category confirmation service.

Bridges the existing ``qc_detection_points`` catalog to the Phase 1 checkpoint
category workflow. For each detection point it ensures a classification row
exists (with a deterministically *proposed* category) and lets a QC supervisor
*confirm* or edit that category.

This is the persistent backing for the UI panel and the
``confirm-category`` API.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.db.qc_model_models import QCCheckpointClassification
from src.db.sku_models import QCDetectionPoint
from src.qc_model.boundary import suggest_category
from src.qc_model.schemas.checkpoint import default_ai_role, is_supported_category


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_classification(
    db: Session,
    detection_point: QCDetectionPoint,
) -> QCCheckpointClassification:
    """Return the classification for a detection point, creating it if absent.

    A new classification is seeded with a *proposed* category derived
    deterministically from the detection point's label/description.
    """
    existing = (
        db.query(QCCheckpointClassification)
        .filter_by(detection_point_id=detection_point.id)
        .first()
    )
    if existing is not None:
        return existing

    proposed = suggest_category(
        f"{detection_point.label} {detection_point.description or ''} "
        f"{detection_point.method_hint or ''}"
    )
    classification = QCCheckpointClassification(
        id=_uid(),
        tenant_id=detection_point.tenant_id,
        sku_id=detection_point.sku_id,
        detection_point_id=detection_point.id,
        proposed_checkpoint_category=proposed,
    )
    db.add(classification)
    db.commit()
    db.refresh(classification)
    return classification


def confirm_category(
    db: Session,
    detection_point_id: str,
    confirmed_category: str,
    confirmed_by: str,
    rationale: str = "",
) -> QCCheckpointClassification:
    """Confirm (or edit) the checkpoint category for a detection point.

    Raises ValueError for an unsupported category or unknown detection point.
    """
    if not is_supported_category(confirmed_category):
        raise ValueError(f"Unsupported checkpoint category: {confirmed_category!r}")

    detection_point = (
        db.query(QCDetectionPoint).filter_by(id=detection_point_id).first()
    )
    if detection_point is None:
        raise ValueError(f"Detection point {detection_point_id!r} not found")

    classification = ensure_classification(db, detection_point)
    classification.confirmed_checkpoint_category = confirmed_category
    classification.category_confirmed_by = confirmed_by
    classification.category_confirmed_at = _now()
    if rationale:
        classification.classification_rationale = rationale
    db.commit()
    db.refresh(classification)
    return classification


def classification_view(classification: QCCheckpointClassification) -> dict:
    """Project a classification into a UI/API-friendly dict."""
    effective = classification.confirmed_checkpoint_category
    return {
        "detection_point_id": classification.detection_point_id,
        "proposed_checkpoint_category": classification.proposed_checkpoint_category,
        "confirmed_checkpoint_category": classification.confirmed_checkpoint_category,
        "category_confirmed_by": classification.category_confirmed_by,
        "category_confirmed_at": (
            classification.category_confirmed_at.isoformat()
            if classification.category_confirmed_at
            else None
        ),
        "classification_rationale": classification.classification_rationale,
        "is_confirmed": classification.is_confirmed(),
        "ai_role": default_ai_role(effective).value,
        "ai_can_be_primary_judge": (
            classification.is_confirmed() and effective == "visual_defect"
        ),
    }
