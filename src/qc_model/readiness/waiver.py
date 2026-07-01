"""Readiness waiver service (PR 24 §4).

A waiver is only valid for the single waivable check (unresolved questions),
requires a supervisor identity and a justification, is scoped to a specific
item, and is appended to an audit log (never mutated). Non-waivable checks
cannot be bypassed even if a waiver is submitted against them.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from src.db.qc_readiness_models import WAIVABLE_CHECK_ID, QCReadinessWaiver


class WaiverValidationError(ValueError):
    pass


def create_waiver(
    db: Session,
    training_pack_id: str,
    item_key: str,
    reason: str,
    supervisor_id: str,
    tenant_id: str = "default",
    check_id: str = WAIVABLE_CHECK_ID,
) -> QCReadinessWaiver:
    """Append a waiver for a single unresolved-question item.

    Rejects: missing supervisor identity, missing justification, a non-waivable
    check_id, or a pack-level blanket waiver (empty item_key).
    """
    if not supervisor_id or not supervisor_id.strip():
        raise WaiverValidationError("waiver requires an authenticated supervisor identity")
    if not reason or not reason.strip():
        raise WaiverValidationError("waiver requires a reason/justification")
    if check_id != WAIVABLE_CHECK_ID:
        raise WaiverValidationError(
            f"check {check_id!r} is not waivable; only {WAIVABLE_CHECK_ID!r} supports a waiver"
        )
    if not item_key or not item_key.strip():
        raise WaiverValidationError(
            "waiver must identify a specific item; pack-level blanket waivers are not permitted"
        )

    waiver = QCReadinessWaiver(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        training_pack_id=training_pack_id,
        check_id=check_id,
        item_key=item_key,
        reason=reason,
        supervisor_id=supervisor_id,
    )
    db.add(waiver)
    db.commit()
    db.refresh(waiver)
    return waiver


def list_waivers(db: Session, training_pack_id: str, tenant_id: str = "default") -> list[QCReadinessWaiver]:
    return (
        db.query(QCReadinessWaiver)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id)
        .order_by(QCReadinessWaiver.created_at.asc())
        .all()
    )
