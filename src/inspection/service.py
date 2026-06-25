"""Inspection lifecycle service — standard revisions and job execution."""
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

_NON_PASS_RESULTS = {"fail", "not_visible", "low_confidence", "missing"}


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
    revision = db.query(QCSkuStandardRevision).filter_by(id=revision_id).one()

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
    db: Session, job_id: str
) -> list[QCDetectionPoint]:
    """Return active detection points for the job's snapshotted standard revision."""
    job = db.query(QCInspectionJob).filter_by(id=job_id).one()
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
    """Record the result for one detection-point checkpoint."""
    job = db.query(QCInspectionJob).filter_by(id=job_id).one()
    tid = tenant_id or job.tenant_id

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
    job = db.query(QCInspectionJob).filter_by(id=job_id).one()
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


def finalize_job(db: Session, job_id: str) -> QCFinalReport:
    """Apply the no-guess QC policy and write a QCFinalReport.

    Policy:
    - Every active detection point for the job's revision must have exactly
      one checkpoint result.  A missing result is treated as 'missing'.
    - Any result of not_visible / low_confidence / missing / fail → cannot pass.
    - All checkpoints pass AND no major/critical incidental findings → pass.
    - All checkpoints pass BUT major/critical incidental finding → review_required.
    - Any checkpoint not pass → fail.
    """
    job = db.query(QCInspectionJob).filter_by(id=job_id).one()
    points = get_active_detection_points_for_job(db, job_id)
    existing_results = (
        db.query(QCCheckpointResult).filter_by(job_id=job_id).all()
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

    all_pass = all(
        result_by_point[pt.id].result == "pass" for pt in points
    ) if points else True

    findings = db.query(QCIncidentalFinding).filter_by(job_id=job_id).all()
    has_serious_finding = any(f.severity in ("major", "critical") for f in findings)

    if not all_pass:
        verdict = "fail"
    elif has_serious_finding:
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
    for pt in points:
        cr = result_by_point.get(pt.id)
        r = cr.result if cr else "missing"
        lines.append(f"  {pt.point_code}: {r}")
    if findings:
        lines.append("Incidental findings:")
        for f in findings:
            lines.append(f"  [{f.severity}] {f.description}")
    return "\n".join(lines)
