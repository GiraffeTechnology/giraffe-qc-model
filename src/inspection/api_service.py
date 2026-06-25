"""Inspection execution API service — thin layer between routers and domain service.

Keeps routers clean. All final-verdict logic lives in src/inspection/service.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.execution_models import (
    QCFinalReport,
    QCIncidentalFinding,
    QCInspectionJob,
    QCModelResult,
)
from src.db.sku_models import QCDetectionPoint, QCSkuItem, QCSkuStandardRevision
from src.inspection.service import (
    create_inspection_job,
    finalize_job,
    get_active_detection_points_for_job,
    submit_checkpoint_result,
    submit_incidental_finding,
)

_VALID_RESULTS = {"pass", "fail", "not_visible", "low_confidence", "unsupported"}


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Job creation ──────────────────────────────────────────────────────────────


def create_inspection_job_from_api(
    db: Session,
    sku_id: str,
    tenant_id: str,
    job_ref: Optional[str] = None,
    created_by: Optional[str] = None,
    notes: Optional[str] = None,
) -> QCInspectionJob:
    """Create an inspection job.  Delegates to domain service."""
    return create_inspection_job(
        db, sku_id=sku_id, tenant_id=tenant_id,
        job_ref=job_ref, created_by=created_by, notes=notes,
    )


# ── Media attachment ──────────────────────────────────────────────────────────


def attach_inspection_media(
    db: Session,
    job_id: str,
    image_url: Optional[str] = None,
    local_path: Optional[str] = None,
    angle: Optional[str] = None,
    view_type: Optional[str] = None,
    sha256: Optional[str] = None,
    width_px: Optional[int] = None,
    height_px: Optional[int] = None,
    mime_type: Optional[str] = None,
    tenant_id: Optional[str] = None,
):
    """Attach media to an existing inspection job."""
    from src.db.execution_models import QCInspectionMedia
    job = db.query(QCInspectionJob).filter_by(id=job_id).one()
    tid = tenant_id or job.tenant_id

    media = QCInspectionMedia(
        id=_uid(),
        job_id=job_id,
        tenant_id=tid,
        image_url=image_url,
        local_path=local_path,
        angle=angle,
        view_type=view_type,
        sha256=sha256,
        width_px=width_px,
        height_px=height_px,
        mime_type=mime_type,
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    return media


# ── Model output ingestion ────────────────────────────────────────────────────


def ingest_model_output(
    db: Session,
    job_id: str,
    provider: str,
    model_name: str,
    raw_output: dict,
    media_id: Optional[str] = None,
    http_status: Optional[int] = None,
    elapsed_ms: Optional[int] = None,
    tenant_id: Optional[str] = None,
) -> QCModelResult:
    """Persist a model result and derive checkpoint results + incidental findings.

    raw_output must contain:
      checkpoint_results: [{point_code, result, observed_value?, confidence?, notes?}]
      incidental_findings: [{severity, description, location_hint?, evidence_json?}]

    Raises ValueError for:
    - unknown point_code (not in job's snapshotted revision)
    - invalid result value
    - duplicate checkpoint result
    """
    job = db.query(QCInspectionJob).filter_by(id=job_id).one()
    tid = tenant_id or job.tenant_id

    # Build point_code → detection_point lookup for this job's revision
    points = get_active_detection_points_for_job(db, job_id)
    code_to_point: dict[str, QCDetectionPoint] = {p.point_code: p for p in points}

    checkpoint_results = raw_output.get("checkpoint_results", [])
    incidental_findings = raw_output.get("incidental_findings", [])

    # Validate before persisting anything
    for cr in checkpoint_results:
        code = cr.get("point_code", "")
        if code not in code_to_point:
            raise ValueError(
                f"Unknown point_code {code!r} in model output. "
                "Model must only reference checkpoints defined in the job's standard revision."
            )
        result_val = cr.get("result", "")
        if result_val not in _VALID_RESULTS:
            raise ValueError(
                f"Invalid checkpoint result {result_val!r} for {code!r}. "
                f"Allowed: {sorted(_VALID_RESULTS)}"
            )

    # Persist model result record
    model_result = QCModelResult(
        id=_uid(),
        job_id=job_id,
        tenant_id=tid,
        media_id=media_id,
        provider=provider,
        model_name=model_name,
        http_status=http_status,
        elapsed_ms=elapsed_ms,
        raw_output=raw_output,
    )
    db.add(model_result)
    db.flush()

    # Persist checkpoint results via domain service (enforces ownership + uniqueness)
    for cr in checkpoint_results:
        code = cr.get("point_code")
        point = code_to_point[code]
        submit_checkpoint_result(
            db,
            job_id=job_id,
            detection_point_id=point.id,
            result=cr["result"],
            observed_value=cr.get("observed_value"),
            confidence=float(cr.get("confidence", 1.0)),
            notes=cr.get("notes"),
            model_result_id=model_result.id,
            tenant_id=tid,
        )

    # Persist incidental findings
    for finding in incidental_findings:
        submit_incidental_finding(
            db,
            job_id=job_id,
            description=finding.get("description", ""),
            severity=finding.get("severity", "minor"),
            location_hint=finding.get("location_hint"),
            evidence_json=finding.get("evidence_json"),
            tenant_id=tid,
        )

    db.commit()
    db.refresh(model_result)
    return model_result


# ── Finalization ──────────────────────────────────────────────────────────────


def finalize_inspection_job(db: Session, job_id: str) -> QCFinalReport:
    """Apply no-guess policy and write final report.  Delegates to domain service."""
    return finalize_job(db, job_id)


# ── Report retrieval ──────────────────────────────────────────────────────────


def get_inspection_report(db: Session, job_id: str) -> QCFinalReport:
    """Return the final report for a completed job.

    Raises ValueError if no report exists (job not yet finalized).
    """
    report = db.query(QCFinalReport).filter_by(job_id=job_id).first()
    if report is None:
        raise ValueError(f"No final report for job {job_id!r}. Call finalize first.")
    return report
