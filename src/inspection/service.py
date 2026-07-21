"""Inspection lifecycle service — standard revisions and job execution."""
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.sku_models import QCSkuStandardRevision, QCDetectionPoint
from src.db.execution_models import (
    QCInspectionJob,
    QCCheckpointResult,
    QCIncidentalFinding,
    QCFinalReport,
    QCAuditEvent,
)

# Results that require human review (cannot observe, but not proved wrong)
_REVIEW_REQUIRED_RESULTS = {"missing", "not_visible", "low_confidence", "unsupported"}
_VALID_CHECKPOINT_RESULTS = {"pass", "fail", "missing", "not_visible", "low_confidence", "unsupported"}
_VALID_FINDING_SEVERITIES = {"minor", "major", "critical"}


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Standard revision lifecycle ──────────────────────────────────────────────


def get_active_standard_revision(
    db: Session, sku_id: str, tenant_id: str
) -> Optional[QCSkuStandardRevision]:
    """Return the single active revision for a SKU, or None."""
    return (
        db.query(QCSkuStandardRevision)
        .filter_by(sku_id=sku_id, tenant_id=tenant_id, status="active")
        .first()
    )


def create_standard_revision(
    db: Session,
    sku_id: str,
    tenant_id: str,
    created_from: str = "admin_ui",
    actor: Optional[str] = None,
    reason: Optional[str] = None,
) -> QCSkuStandardRevision:
    """Create a new draft revision; does NOT archive the current active one yet."""
    last = (
        db.query(QCSkuStandardRevision)
        .filter_by(sku_id=sku_id, tenant_id=tenant_id)
        .order_by(QCSkuStandardRevision.revision_no.desc())
        .first()
    )
    next_no = (last.revision_no + 1) if last else 1

    revision = QCSkuStandardRevision(
        id=_uid(),
        sku_id=sku_id,
        tenant_id=tenant_id,
        revision_no=next_no,
        status="draft",
        created_from=created_from,
        updated_by_operator=actor,
        last_update_reason=reason,
    )
    db.add(revision)
    db.flush()

    db.add(QCAuditEvent(
        id=_uid(),
        tenant_id=tenant_id,
        entity_type="standard_revision",
        entity_id=revision.id,
        event_type="created",
        actor=actor,
        details_json={"revision_no": next_no, "reason": reason},
    ))
    db.commit()
    db.refresh(revision)
    return revision


def confirm_standard_revision(
    db: Session,
    revision_id: str,
    confirmed_by: str,
    tenant_id: str,
) -> QCSkuStandardRevision:
    """Activate a draft/pending_confirmation revision, archiving the prior active one."""
    revision = db.query(QCSkuStandardRevision).filter_by(id=revision_id, tenant_id=tenant_id).one()

    # Archive the previously active revision
    prior = (
        db.query(QCSkuStandardRevision)
        .filter_by(sku_id=revision.sku_id, tenant_id=tenant_id, status="active")
        .first()
    )
    if prior and prior.id != revision_id:
        prior.status = "archived"
        prior.superseded_by_revision = revision.revision_no
        db.add(QCAuditEvent(
            id=_uid(),
            tenant_id=tenant_id,
            entity_type="standard_revision",
            entity_id=prior.id,
            event_type="archived",
            actor=confirmed_by,
            details_json={"superseded_by": revision.revision_no},
        ))
        db.flush()

    revision.status = "active"
    revision.confirmed_by = confirmed_by
    revision.confirmed_at = _now()
    db.add(QCAuditEvent(
        id=_uid(),
        tenant_id=tenant_id,
        entity_type="standard_revision",
        entity_id=revision.id,
        event_type="confirmed",
        actor=confirmed_by,
        details_json={"revision_no": revision.revision_no},
    ))
    db.commit()
    db.refresh(revision)
    return revision


# ── Inspection job lifecycle ─────────────────────────────────────────────────


def create_inspection_job(
    db: Session,
    sku_id: str,
    tenant_id: str,
    job_ref: Optional[str] = None,
    created_by: Optional[str] = None,
    notes: Optional[str] = None,
) -> QCInspectionJob:
    """Create a new inspection job, snapshotting the current active revision.

    Raises ValueError if no active revision exists for the SKU.
    """
    revision = get_active_standard_revision(db, sku_id, tenant_id)
    if revision is None:
        raise ValueError(
            f"No active standard revision for sku_id={sku_id!r}. "
            "Confirm a revision before creating inspection jobs."
        )

    job = QCInspectionJob(
        id=_uid(),
        tenant_id=tenant_id,
        sku_id=sku_id,
        active_standard_revision_id=revision.id,
        job_ref=job_ref,
        status="pending",
        created_by=created_by,
        notes=notes,
    )
    db.add(job)
    db.add(QCAuditEvent(
        id=_uid(),
        tenant_id=tenant_id,
        entity_type="job",
        entity_id=job.id,
        event_type="created",
        actor=created_by,
        details_json={"revision_no": revision.revision_no},
    ))
    db.commit()
    db.refresh(job)
    return job


def get_active_detection_points_for_job(
    db: Session, job_id: str, tenant_id: Optional[str] = None
) -> list[QCDetectionPoint]:
    """Return active detection points for the job's snapshotted standard revision."""
    filters = {"id": job_id}
    if tenant_id is not None:
        filters["tenant_id"] = tenant_id
    job = db.query(QCInspectionJob).filter_by(**filters).one()
    return (
        db.query(QCDetectionPoint)
        .filter_by(
            standard_revision_id=job.active_standard_revision_id,
            is_active=True,
        )
        .order_by(QCDetectionPoint.sort_order)
        .all()
    )


def submit_checkpoint_result(
    db: Session,
    job_id: str,
    detection_point_id: str,
    result: str,
    observed_value: Optional[str] = None,
    confidence: float = 1.0,
    notes: Optional[str] = None,
    model_result_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> QCCheckpointResult:
    """Record the result for one detection-point checkpoint.

    Raises ValueError if:
    - the detection point does not exist or is inactive
    - the detection point does not belong to the job's snapshotted revision/SKU/tenant
    - a result for this (job_id, detection_point_id) pair already exists
    """
    if result not in _VALID_CHECKPOINT_RESULTS:
        raise ValueError(f"Invalid checkpoint result {result!r}. Allowed: {sorted(_VALID_CHECKPOINT_RESULTS)}")

    job_filters = {"id": job_id}
    if tenant_id is not None:
        job_filters["tenant_id"] = tenant_id
    job = db.query(QCInspectionJob).filter_by(**job_filters).one()
    tid = tenant_id or job.tenant_id

    # Validate detection point belongs to this job's snapshotted revision
    point = db.query(QCDetectionPoint).filter_by(id=detection_point_id).first()
    if point is None:
        raise ValueError(f"Detection point {detection_point_id!r} not found.")
    if point.tenant_id != job.tenant_id:
        raise ValueError(
            f"Detection point {detection_point_id!r} belongs to tenant {point.tenant_id!r}, "
            f"not the job's tenant {job.tenant_id!r}."
        )
    if point.sku_id != job.sku_id:
        raise ValueError(
            f"Detection point {detection_point_id!r} belongs to SKU {point.sku_id!r}, "
            f"not the job's SKU {job.sku_id!r}."
        )
    if point.standard_revision_id != job.active_standard_revision_id:
        raise ValueError(
            f"Detection point {detection_point_id!r} belongs to revision "
            f"{point.standard_revision_id!r}, not the job's snapshotted revision "
            f"{job.active_standard_revision_id!r}."
        )
    if not point.is_active:
        raise ValueError(
            f"Detection point {detection_point_id!r} is not active."
        )

    # Reject duplicate results for the same (job, detection_point) pair
    existing = (
        db.query(QCCheckpointResult)
        .filter_by(job_id=job_id, detection_point_id=detection_point_id)
        .first()
    )
    if existing is not None:
        raise ValueError(
            f"A checkpoint result for detection_point_id={detection_point_id!r} already exists "
            f"on job {job_id!r}. Cannot submit duplicate checkpoint results."
        )

    cr = QCCheckpointResult(
        id=_uid(),
        job_id=job_id,
        tenant_id=tid,
        detection_point_id=detection_point_id,
        model_result_id=model_result_id,
        result=result,
        observed_value=observed_value,
        confidence=confidence,
        notes=notes,
    )
    db.add(cr)
    db.commit()
    db.refresh(cr)
    return cr


def submit_checkpoint_results_batch(
    db: Session,
    job_id: str,
    results: list[dict],
    tenant_id: Optional[str] = None,
) -> list[QCCheckpointResult]:
    """Atomically record one operator result for every active checkpoint.

    The Web Pad simulator uses this transaction so a partial browser request can
    never leave a job with half of its submitted decisions persisted.  The set of
    submitted detection points must exactly match the job's snapshotted active
    revision; missing, unknown, duplicate, or previously submitted points fail
    closed before any row is written.
    """
    job_filters = {"id": job_id}
    if tenant_id is not None:
        job_filters["tenant_id"] = tenant_id
    job = db.query(QCInspectionJob).filter_by(**job_filters).one()
    points = get_active_detection_points_for_job(db, job_id, tenant_id=job.tenant_id)
    if not points:
        raise ValueError("Inspection job has no active detection points; cannot submit a pass.")
    if not job.media:
        raise ValueError("Inspection job has no attached evidence; checkpoint submission blocked.")
    if not all(isinstance(item, dict) for item in results):
        raise TypeError("Each checkpoint result must be an object.")

    point_by_id = {point.id: point for point in points}
    submitted_ids = [str(item.get("detection_point_id", "")) for item in results]
    if len(submitted_ids) != len(set(submitted_ids)):
        raise ValueError("Duplicate detection_point_id in checkpoint result batch.")

    expected_ids = set(point_by_id)
    provided_ids = set(submitted_ids)
    missing = sorted(expected_ids - provided_ids)
    unknown = sorted(provided_ids - expected_ids)
    if missing or unknown:
        raise ValueError(
            "Checkpoint batch must exactly match the active revision "
            f"(missing={missing}, unknown={unknown})."
        )

    invalid = sorted(
        {
            str(item.get("result", ""))
            for item in results
            if str(item.get("result", "")) not in _VALID_CHECKPOINT_RESULTS
        }
    )
    if invalid:
        raise ValueError(
            f"Invalid checkpoint result(s) {invalid}. Allowed: {sorted(_VALID_CHECKPOINT_RESULTS)}"
        )

    normalized_confidence: list[float] = []
    for item in results:
        try:
            confidence = float(item.get("confidence", 1.0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Checkpoint confidence must be a number between 0 and 1.") from exc
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            raise ValueError("Checkpoint confidence must be a finite number between 0 and 1.")
        normalized_confidence.append(confidence)

    existing = (
        db.query(QCCheckpointResult)
        .filter(
            QCCheckpointResult.job_id == job_id,
            QCCheckpointResult.tenant_id == job.tenant_id,
        )
        .first()
    )
    if existing is not None:
        raise ValueError("Checkpoint results already exist for this job; duplicate submission blocked.")

    rows = [
        QCCheckpointResult(
            id=_uid(),
            job_id=job_id,
            tenant_id=job.tenant_id,
            detection_point_id=str(item["detection_point_id"]),
            result=str(item["result"]),
            observed_value=item.get("observed_value"),
            confidence=normalized_confidence[index],
            notes=item.get("notes"),
        )
        for index, item in enumerate(results)
    ]
    db.add_all(rows)
    db.commit()
    for row in rows:
        db.refresh(row)
    return rows


def submit_incidental_finding(
    db: Session,
    job_id: str,
    description: str,
    severity: str = "minor",
    location_hint: Optional[str] = None,
    evidence_json: Optional[dict] = None,
    tenant_id: Optional[str] = None,
) -> QCIncidentalFinding:
    """Record an incidental finding (defect not tied to a named checkpoint)."""
    if severity not in _VALID_FINDING_SEVERITIES:
        raise ValueError(f"Invalid finding severity {severity!r}. Allowed: {sorted(_VALID_FINDING_SEVERITIES)}")

    job_filters = {"id": job_id}
    if tenant_id is not None:
        job_filters["tenant_id"] = tenant_id
    job = db.query(QCInspectionJob).filter_by(**job_filters).one()
    tid = tenant_id or job.tenant_id

    finding = QCIncidentalFinding(
        id=_uid(),
        job_id=job_id,
        tenant_id=tid,
        description=description,
        severity=severity,
        location_hint=location_hint,
        evidence_json=evidence_json,
    )
    db.add(finding)
    db.commit()
    db.refresh(finding)
    return finding


def finalize_job(db: Session, job_id: str, tenant_id: Optional[str] = None) -> QCFinalReport:
    """Apply the no-guess QC policy and write a QCFinalReport.

    Policy:
    - Every active detection point for the job's revision must have exactly
      one checkpoint result.  A missing result is auto-inserted as 'missing'.
    - result == 'fail' → verdict = 'fail'
    - result in {missing, not_visible, low_confidence, unsupported} → verdict = 'review_required'
    - All checkpoints 'pass' AND major/critical incidental finding → 'review_required'
    - All checkpoints 'pass' AND no serious finding → 'pass'

    Idempotent: if a final report already exists for a completed job, returns it unchanged.
    """
    job_filters = {"id": job_id}
    if tenant_id is not None:
        job_filters["tenant_id"] = tenant_id
    job = db.query(QCInspectionJob).filter_by(**job_filters).one()

    # Idempotency: return existing report if job is already finalized
    report_filters = {"job_id": job_id}
    if tenant_id is not None:
        report_filters["tenant_id"] = tenant_id
    existing_report = db.query(QCFinalReport).filter_by(**report_filters).first()
    if existing_report is not None and job.status in ("pass", "fail", "review_required"):
        return existing_report

    points = get_active_detection_points_for_job(db, job_id, tenant_id=job.tenant_id)
    existing_results = (
        db.query(QCCheckpointResult).filter_by(job_id=job_id, tenant_id=job.tenant_id).all()
    )
    result_by_point = {cr.detection_point_id: cr for cr in existing_results}

    # Ensure a checkpoint result exists for every active point (insert 'missing' if absent)
    for pt in points:
        if pt.id not in result_by_point:
            cr = QCCheckpointResult(
                id=_uid(),
                job_id=job_id,
                tenant_id=job.tenant_id,
                detection_point_id=pt.id,
                result="missing",
                confidence=0.0,
                notes="Auto-inserted by finalize_job: no result submitted.",
            )
            db.add(cr)
            result_by_point[pt.id] = cr
    db.flush()

    has_fail = any(result_by_point[pt.id].result == "fail" for pt in points)
    has_review_required = any(
        result_by_point[pt.id].result in _REVIEW_REQUIRED_RESULTS for pt in points
    )

    findings = db.query(QCIncidentalFinding).filter_by(job_id=job_id, tenant_id=job.tenant_id).all()
    has_serious_finding = any(f.severity in ("major", "critical") for f in findings)

    if not points:
        verdict = "review_required"
    elif has_fail:
        verdict = "fail"
    elif has_review_required or has_serious_finding:
        verdict = "review_required"
    else:
        verdict = "pass"

    report = QCFinalReport(
        id=_uid(),
        job_id=job_id,
        tenant_id=job.tenant_id,
        overall_result=verdict,
        checkpoint_results_count=len(points),
        findings_count=len(findings),
        summary_text=_build_summary(points, result_by_point, findings, verdict),
    )
    db.add(report)

    job.status = verdict
    job.completed_at = datetime.now(timezone.utc)
    db.add(QCAuditEvent(
        id=_uid(),
        tenant_id=job.tenant_id,
        entity_type="job",
        entity_id=job_id,
        event_type="job_finalized",
        details_json={"verdict": verdict, "checkpoints": len(points), "findings": len(findings)},
    ))
    db.commit()
    db.refresh(report)
    return report


def _build_summary(points, result_by_point, findings, verdict: str) -> str:
    lines = [f"Verdict: {verdict}"]
    if not points:
        lines.append("No active detection points are defined for this job's standard revision.")
    for pt in points:
        cr = result_by_point.get(pt.id)
        r = cr.result if cr else "missing"
        lines.append(f"  {pt.point_code}: {r}")
    if findings:
        lines.append("Incidental findings:")
        for f in findings:
            lines.append(f"  [{f.severity}] {f.description}")
    return "\n".join(lines)
