"""Preset Stage 2 operator workflow state, derived from persisted evidence.

The PRD defines inspection as an ordered workflow — capture evidence, run the
configured CV → VLM analysis, review every checkpoint as a human, finalize on
the server, review the report — not a bag of endpoints. This module derives
each step's completion from the database so the UI and acceptance runs can
show exactly where a job stands, and so skipped steps are visible instead of
silent. Enforcement lives in the endpoints themselves (media required before
analysis, human review required before a pass verdict); this is the auditable
view of that ordering.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from src.db.execution_models import (
    QCCheckpointResult,
    QCFinalReport,
    QCInspectionJob,
    QCInspectionMedia,
    QCModelResult,
)
from src.inspection.service import get_active_detection_points_for_job

STEPS = (
    "standard_active",
    "evidence_attached",
    "vision_analyzed",
    "operator_reviewed",
    "finalized",
)

# PRD Authoring Extension §3.1 lifecycle, as a single derived view. The
# underlying facts live on four entities (revision status, publish bundles,
# workstation installs, probation records); this maps them back onto the PRD
# state chain so "where is this standard in its lifecycle" has one answer.
LIFECYCLE_STAGES = (
    "draft",
    "ready_for_review",
    "confirmed",
    "published",
    "installed_on_pad",
    "probation",
    "active_inspection",
)


def derive_standard_lifecycle(
    db: Session, sku_id: str, tenant_id: str
) -> dict[str, Any]:
    """Derive the PRD-vocabulary lifecycle stage for a SKU's standard."""
    from src.db.sku_models import QCSkuStandardRevision
    from src.db.studio_models import QCPublishBundle
    from src.db.qc_bundle_models import QCBundle, QCBundleAssignment, QCWorkstation
    from src.qc_model.qualification import probation as _probation

    active = (
        db.query(QCSkuStandardRevision)
        .filter_by(sku_id=sku_id, tenant_id=tenant_id, status="active")
        .order_by(QCSkuStandardRevision.revision_no.desc())
        .first()
    )
    if active is None:
        pending = (
            db.query(QCSkuStandardRevision)
            .filter(
                QCSkuStandardRevision.sku_id == sku_id,
                QCSkuStandardRevision.tenant_id == tenant_id,
                QCSkuStandardRevision.status.in_(("draft", "pending_confirmation")),
            )
            .first()
        )
        stage = "ready_for_review" if pending is not None else "draft"
        return {"stage": stage, "standard_revision_id": None}

    stage = "confirmed"
    published = (
        db.query(QCPublishBundle)
        .filter_by(tenant_id=tenant_id, sku_id=sku_id, standard_revision_id=active.id)
        .first()
    )
    if published is not None:
        stage = "published"

        # Best-effort install detection: a workstation reports the same
        # bundle_version it was assigned, for a distribution bundle whose
        # manifest carries this revision.
        installed = (
            db.query(QCBundleAssignment)
            .join(QCWorkstation, QCBundleAssignment.workstation_pk == QCWorkstation.id)
            .join(QCBundle, QCBundleAssignment.bundle_pk == QCBundle.id)
            .filter(
                QCBundleAssignment.tenant_id == tenant_id,
                QCWorkstation.installed_bundle_version
                == QCBundleAssignment.bundle_version,
            )
            .all()
        )
        if any(active.id in str(a.bundle.manifest_json) for a in installed):
            stage = "installed_on_pad"

    probation = _probation.get_probation_for_revision(db, active.id, tenant_id)
    if probation is not None:
        if probation.status == _probation.PROBATION_QUALIFIED:
            stage = "active_inspection"
        else:
            stage = "probation"

    return {
        "stage": stage,
        "standard_revision_id": active.id,
        "revision_no": active.revision_no,
        "probation_status": probation.status if probation else None,
    }


def derive_workflow_state(
    db: Session, job: QCInspectionJob, tenant_id: Optional[str] = None
) -> dict[str, Any]:
    tid = tenant_id or job.tenant_id

    media_count = (
        db.query(QCInspectionMedia).filter_by(job_id=job.id, tenant_id=tid).count()
    )
    model_result_count = (
        db.query(QCModelResult).filter_by(job_id=job.id, tenant_id=tid).count()
    )
    points = get_active_detection_points_for_job(db, job.id, tenant_id=tid)
    checkpoint_results = (
        db.query(QCCheckpointResult).filter_by(job_id=job.id, tenant_id=tid).all()
    )
    reviewed = [
        r for r in checkpoint_results
        if getattr(r, "review_source", "model") == "operator"
    ]
    report = db.query(QCFinalReport).filter_by(job_id=job.id, tenant_id=tid).first()

    operator_reviewed = bool(points) and len(reviewed) == len(points)

    steps = [
        {
            "step": "standard_active",
            "done": True,
            "detail": {
                "standard_revision_id": job.active_standard_revision_id,
                "detection_point_count": len(points),
            },
        },
        {
            "step": "evidence_attached",
            "done": media_count > 0,
            "detail": {"media_count": media_count},
        },
        {
            "step": "vision_analyzed",
            "done": model_result_count > 0,
            "detail": {"model_result_count": model_result_count},
        },
        {
            "step": "operator_reviewed",
            "done": operator_reviewed,
            "detail": {
                "reviewed_checkpoints": len(reviewed),
                "required_checkpoints": len(points),
            },
        },
        {
            "step": "finalized",
            "done": report is not None,
            "detail": {
                "overall_result": report.overall_result if report else None,
            },
        },
    ]

    next_step = next((s["step"] for s in steps if not s["done"]), None)
    return {
        "job_id": job.id,
        "sku_id": job.sku_id,
        "status": job.status,
        "steps": steps,
        "next_step": next_step,
        "workflow_complete": next_step is None,
        "standard_lifecycle": derive_standard_lifecycle(db, job.sku_id, tid),
    }
