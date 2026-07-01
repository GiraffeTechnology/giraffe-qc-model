"""Apply approved learned proposals to the Training Pack (PRD §17).

Rules enforced:
1. Only ``approved`` proposals can be applied.
2. Rejected / proposed-only proposals are never applied.
3. Applied detection points preserve traceability to the learning job and the
   supervisor approval (proposal keeps ``applied_detection_point_id``,
   ``approved_by``, ``approved_at``; an ``apply`` approval row is recorded).
4. The original operator requirement is preserved on the proposal.
5. Applying rules never auto-activates a Training Pack or inspector.
6. Physical-measurement proposals are applied as record-only (their confirmed
   category is ``physical_measurement``, which is never AI-primary).
7. Applying is idempotent — an already-applied proposal is skipped.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from src.db.qc_learning_models import (
    QCLearnedDetectionPointProposal,
    QCLearningApproval,
    QCLearningJob,
)
from src.db.qc_model_models import QCCheckpointClassification
from src.db.sku_models import QCDetectionPoint
from src.qc_model.learning.schemas import LearningJobStatus, ProposalStatus
from src.qc_model.learning.service import get_job


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def apply_approved_rules(
    db: Session,
    learning_job_id: str,
    applied_by: str,
    tenant_id: str = "default",
) -> dict:
    """Apply all approved proposals for a job. Idempotent."""
    job = get_job(db, learning_job_id, tenant_id)

    proposals = (
        db.query(QCLearnedDetectionPointProposal)
        .filter_by(learning_job_id=job.id, tenant_id=tenant_id)
        .all()
    )

    applied: list[str] = []
    skipped: list[dict] = []

    for p in proposals:
        # Idempotency: already applied.
        if p.status == ProposalStatus.APPLIED.value or p.applied_detection_point_id:
            skipped.append({"proposal_id": p.id, "reason": "already_applied"})
            continue
        # Only approved proposals may be applied.
        if p.status != ProposalStatus.APPROVED.value:
            skipped.append({"proposal_id": p.id, "reason": f"not_approved:{p.status}"})
            continue

        detection_point = QCDetectionPoint(
            id=_uid(),
            tenant_id=job.tenant_id,
            sku_id=job.sku_id,
            point_code=p.proposed_code,
            label=p.proposed_name or p.proposed_code,
            description=p.decision_rule,
            severity=p.severity,
            method_hint=p.proposed_ai_role,
            is_active=True,
        )
        db.add(detection_point)
        db.flush()  # get detection_point.id

        # Confirmed category classification (Phase 1 overlay). The approved
        # category becomes the confirmed category; physical_measurement stays
        # record-only (never AI-primary).
        db.add(
            QCCheckpointClassification(
                id=_uid(),
                tenant_id=job.tenant_id,
                sku_id=job.sku_id,
                detection_point_id=detection_point.id,
                proposed_checkpoint_category=p.proposed_checkpoint_category,
                confirmed_checkpoint_category=p.proposed_checkpoint_category,
                category_confirmed_by=applied_by,
                category_confirmed_at=_now(),
                classification_rationale=(
                    f"Applied from learning job {job.id} "
                    f"(approved by {p.approved_by}). "
                    f"Original requirement: {p.source_requirement or 'n/a'}"
                ),
            )
        )

        p.status = ProposalStatus.APPLIED.value
        p.applied_detection_point_id = detection_point.id
        db.add(
            QCLearningApproval(
                id=_uid(),
                tenant_id=job.tenant_id,
                learning_job_id=job.id,
                proposal_type="detection_point",
                proposal_id=p.id,
                action="apply",
                reviewer_id=applied_by,
            )
        )
        applied.append(p.id)

    # Move the job to applied only when there is at least one proposal and every
    # proposal is applied; otherwise it stays as-is. An empty/draft job (no
    # proposals) must never be marked applied. Never auto-activate any Training
    # Pack/inspector.
    remaining = [
        pr for pr in proposals if pr.status != ProposalStatus.APPLIED.value
    ]
    if proposals and not remaining:
        job.status = LearningJobStatus.APPLIED.value

    db.commit()
    db.refresh(job)
    return {
        "learning_job_id": job.id,
        "job_status": job.status,
        "applied_proposal_ids": applied,
        "skipped": skipped,
        "training_pack_auto_activated": False,
    }
