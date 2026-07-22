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
    }
