"""Inspection execution API service — thin layer between routers and domain service.

Keeps routers clean. All final-verdict logic lives in src/inspection/service.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.execution_models import (
    QCCheckpointResult,
    QCFinalReport,
    QCIncidentalFinding,
    QCInspectionJob,
    QCModelResult,
)
from src.db.sku_models import QCDetectionPoint
from src.inspection.service import (
    create_inspection_job,
    finalize_job,
    get_active_detection_points_for_job,
)

_VALID_RESULTS = {"pass", "fail", "not_visible", "low_confidence", "unsupported", "missing"}
_VALID_SEVERITIES = {"minor", "major", "critical"}


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
    job_filters = {"id": job_id}
    if tenant_id is not None:
        job_filters["tenant_id"] = tenant_id
    job = db.query(QCInspectionJob).filter_by(**job_filters).one()
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
    - duplicate point_code within the payload
    - a QCCheckpointResult already exists for any detection_point in this job
    - media_id provided but does not belong to this job
    - tenant_id provided but does not match job.tenant_id

    All validation runs BEFORE any persistence so the operation is fully atomic.
    """
    from src.db.execution_models import QCInspectionMedia

    job_filters = {"id": job_id}
    if tenant_id is not None:
        job_filters["tenant_id"] = tenant_id
    job = db.query(QCInspectionJob).filter_by(**job_filters).one()
    tid = tenant_id or job.tenant_id

    # Check 6: tenant_id mismatch
    if tenant_id is not None and tenant_id != job.tenant_id:
        raise ValueError(
            f"Provided tenant_id {tenant_id!r} does not match job's tenant_id {job.tenant_id!r}."
        )

    # Check 5: media_id must belong to this job
    if media_id is not None:
        media_row = (
            db.query(QCInspectionMedia)
            .filter_by(id=media_id, job_id=job_id, tenant_id=job.tenant_id)
            .first()
        )
        if media_row is None:
            raise ValueError(
                f"media_id {media_id!r} does not belong to job {job_id!r}. "
                "media must be attached to the same inspection job."
            )

    # Build point_code → detection_point lookup for this job's revision
    points = get_active_detection_points_for_job(db, job_id, tenant_id=job.tenant_id)
    code_to_point: dict[str, QCDetectionPoint] = {p.point_code: p for p in points}

    checkpoint_results = raw_output.get("checkpoint_results", [])
    incidental_findings = raw_output.get("incidental_findings", [])

    # Check 3: detect duplicate point_codes within the payload
    seen_codes: set[str] = set()
    for cr in checkpoint_results:
        code = cr.get("point_code", "")
        if code in seen_codes:
            raise ValueError(
                f"Duplicate point_code {code!r} in model output payload. "
                "Each checkpoint may only appear once per model output submission."
            )
        seen_codes.add(code)

    # Checks 1 & 2: unknown point_code and invalid result values
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

    for finding in incidental_findings:
        severity = finding.get("severity", "minor")
        if severity not in _VALID_SEVERITIES:
            raise ValueError(
                f"Invalid incidental finding severity {severity!r}. "
                f"Allowed: {sorted(_VALID_SEVERITIES)}"
            )

    # Check 4: no QCCheckpointResult already exists for any of these detection points in this job
    for cr in checkpoint_results:
        code = cr.get("point_code", "")
        point = code_to_point[code]
        existing = (
            db.query(QCCheckpointResult)
            .filter_by(job_id=job_id, detection_point_id=point.id)
            .first()
        )
        if existing is not None:
            raise ValueError(
                f"A checkpoint result for point_code {code!r} (detection_point_id={point.id!r}) "
                f"already exists on job {job_id!r}. Cannot submit duplicate checkpoint results."
            )

    # --- All checks passed; persist everything in one transaction ---

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

    # Persist checkpoint results directly (no per-row commit)
    for cr in checkpoint_results:
        code = cr.get("point_code")
        point = code_to_point[code]
        checkpoint_result = QCCheckpointResult(
            id=_uid(),
            job_id=job_id,
            tenant_id=tid,
            detection_point_id=point.id,
            model_result_id=model_result.id,
            result=cr["result"],
            observed_value=cr.get("observed_value"),
            confidence=float(cr.get("confidence", 1.0)),
            notes=cr.get("notes"),
        )
        db.add(checkpoint_result)

    # Persist incidental findings directly (no per-row commit)
    for finding in incidental_findings:
        incidental = QCIncidentalFinding(
            id=_uid(),
            job_id=job_id,
            tenant_id=tid,
            description=finding.get("description", ""),
            severity=finding.get("severity", "minor"),
            location_hint=finding.get("location_hint"),
            evidence_json=finding.get("evidence_json"),
        )
        db.add(incidental)

    db.commit()
    db.refresh(model_result)
    return model_result


# ── Finalization ──────────────────────────────────────────────────────────────


def finalize_inspection_job(
    db: Session,
    job_id: str,
    tenant_id: Optional[str] = None,
    require_human_review: bool = False,
) -> QCFinalReport:
    """Apply no-guess policy and write final report.  Delegates to domain service."""
    return finalize_job(
        db, job_id, tenant_id=tenant_id, require_human_review=require_human_review
    )


# ── Report retrieval ──────────────────────────────────────────────────────────


def get_inspection_report(db: Session, job_id: str, tenant_id: Optional[str] = None) -> QCFinalReport:
    """Return the final report for a completed job.

    Raises ValueError if no report exists (job not yet finalized).
    """
    report_filters = {"job_id": job_id}
    if tenant_id is not None:
        report_filters["tenant_id"] = tenant_id
    report = db.query(QCFinalReport).filter_by(**report_filters).first()
    if report is None:
        raise ValueError(f"No final report for job {job_id!r}. Call finalize first.")
    return report
