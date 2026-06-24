"""Inspection job service.

Runs checkpoint inspection and derives final result per the no-guess policy.
Final result can never be 'pass' unless:
  - all checkpoints are observed and passed
  - coverage_rate == 100%
  - no major or critical incidental findings
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from src.db.qc_checkpoint_models import (
    QCInspectionJob, QCInspectionMedia, QCMediaAsset, QCModelResult,
    QCCheckpointResult, QCIncidentalFinding, QCFinalReport, QCAuditEvent,
    QCCheckPoint
)


def create_inspection_job(
    db: Session,
    *,
    sku_id: int,
    standard_version_id: int,
    batch_no: Optional[str] = None,
    operator_id: Optional[str] = None,
    runtime_type: str = "server_model",
) -> QCInspectionJob:
    total = (
        db.query(QCCheckPoint)
        .filter_by(standard_version_id=standard_version_id)
        .count()
    )
    job = QCInspectionJob(
        sku_id=sku_id,
        standard_version_id=standard_version_id,
        batch_no=batch_no,
        operator_id=operator_id,
        inspection_status="created",
        runtime_type=runtime_type,
        checkpoint_total=total,
    )
    db.add(job)
    db.commit()
    return job


def attach_inspection_media(
    db: Session,
    *,
    inspection_job: QCInspectionJob,
    media_asset: QCMediaAsset,
    view_type: str = "front",
    is_primary: bool = False,
) -> QCInspectionMedia:
    media = QCInspectionMedia(
        inspection_job_id=inspection_job.id,
        media_asset_id=media_asset.id,
        view_type=view_type,
        is_primary=is_primary,
    )
    db.add(media)
    inspection_job.inspection_status = "media_uploaded"
    db.commit()
    return media


def save_checkpoint_results(
    db: Session,
    *,
    inspection_job: QCInspectionJob,
    results: list[dict],
) -> list[QCCheckpointResult]:
    """Persist per-checkpoint results and update job counters.

    Each dict in results must include: checkpoint_id, checkpoint_code,
    checkpoint_name, result (pass/fail/review_required).
    Optional keys: expected_json, observed_json, comparison_json,
    confidence_score, evidence_type, evidence_json, verification_status,
    failure_reason.
    """
    inspection_job.inspection_status = "model_running"
    db.flush()

    saved: list[QCCheckpointResult] = []
    for r in results:
        cp_result = QCCheckpointResult(
            inspection_job_id=inspection_job.id,
            checkpoint_id=r["checkpoint_id"],
            checkpoint_code=r["checkpoint_code"],
            checkpoint_name=r["checkpoint_name"],
            expected_json=r.get("expected_json"),
            observed_json=r.get("observed_json"),
            comparison_json=r.get("comparison_json"),
            result=r["result"],
            confidence_score=r.get("confidence_score", 1.0),
            evidence_type=r.get("evidence_type", "none"),
            evidence_json=r.get("evidence_json"),
            verification_status=r.get("verification_status", "observed"),
            failure_reason=r.get("failure_reason"),
        )
        db.add(cp_result)
        saved.append(cp_result)

    db.flush()
    _update_job_counters(inspection_job, saved)
    inspection_job.inspection_status = "ai_done"
    db.commit()
    return saved


def save_model_result(
    db: Session,
    *,
    inspection_job: QCInspectionJob,
    overall_result: str,
    model_name: str = "mock",
    model_version: str = "test",
    runtime_type: str = "server_model",
    overall_confidence: Optional[float] = None,
    raw_output_json: Optional[dict] = None,
    manual_review_reason: Optional[str] = None,
    unsupported_checkpoints_json: Optional[dict] = None,
    low_confidence_checkpoints_json: Optional[dict] = None,
) -> QCModelResult:
    model_result = QCModelResult(
        inspection_job_id=inspection_job.id,
        model_name=model_name,
        model_version=model_version,
        runtime_type=runtime_type,
        overall_result=overall_result,
        overall_confidence=overall_confidence,
        no_guess_policy_applied=True,
        unsupported_checkpoints_json=unsupported_checkpoints_json,
        low_confidence_checkpoints_json=low_confidence_checkpoints_json,
        manual_review_reason=manual_review_reason,
        raw_output_json=raw_output_json,
    )
    db.add(model_result)
    db.commit()
    return model_result


def run_checkpoint_inspection(
    db: Session,
    inspection_job: QCInspectionJob,
    checkpoint_observations: list[dict],
) -> list[QCCheckpointResult]:
    """Convenience wrapper: save observations and return results.

    checkpoint_observations is the same format as save_checkpoint_results.
    """
    return save_checkpoint_results(
        db, inspection_job=inspection_job, results=checkpoint_observations
    )


def save_incidental_findings(
    db: Session,
    *,
    inspection_job: QCInspectionJob,
    findings: list[dict],
) -> list[QCIncidentalFinding]:
    """Persist abnormalities detected outside the approved checklist."""
    saved: list[QCIncidentalFinding] = []
    for f in findings:
        finding = QCIncidentalFinding(
            inspection_job_id=inspection_job.id,
            finding_type=f["finding_type"],
            target_part=f.get("target_part"),
            finding_text=f.get("finding_text"),
            severity=f.get("severity", "minor"),
            confidence_score=f.get("confidence_score"),
            is_within_approved_checklist=f.get("is_within_approved_checklist", False),
            requires_human_review=f.get("requires_human_review", False),
            evidence_json=f.get("evidence_json"),
        )
        db.add(finding)
        saved.append(finding)

    db.flush()
    _update_finding_counters(inspection_job, saved)
    db.commit()
    return saved


def derive_final_result(
    db: Session,
    inspection_job: QCInspectionJob,
) -> str:
    """Derive final result per the no-guess policy.

    Returns 'pass', 'fail', or 'review_required'.
    Never returns 'pass' unless every checkpoint is observed and passed
    and there are no major/critical incidental findings.
    """
    cp_results = (
        db.query(QCCheckpointResult)
        .filter_by(inspection_job_id=inspection_job.id)
        .all()
    )
    findings = (
        db.query(QCIncidentalFinding)
        .filter_by(inspection_job_id=inspection_job.id)
        .all()
    )
    checkpoints = (
        db.query(QCCheckPoint)
        .filter_by(standard_version_id=inspection_job.standard_version_id)
        .all()
    )
    checkpoint_severity = {cp.id: cp.severity for cp in checkpoints}

    # Missing coverage → review_required (no-guess policy)
    if len(cp_results) < inspection_job.checkpoint_total:
        inspection_job.has_unchecked_checkpoint = True
        inspection_job.coverage_rate = (
            len(cp_results) / inspection_job.checkpoint_total
            if inspection_job.checkpoint_total > 0
            else 0.0
        )
        _set_status(inspection_job, "review_required")
        db.commit()
        return "review_required"

    # Any unobserved checkpoint → review_required
    for r in cp_results:
        if r.verification_status != "observed":
            _set_status(inspection_job, "review_required")
            db.commit()
            return "review_required"

    # Evaluate checkpoint pass/fail by severity
    for r in cp_results:
        if r.result == "fail":
            _set_status(inspection_job, "fail")
            db.commit()
            return "fail"

    for r in cp_results:
        if r.result == "review_required":
            _set_status(inspection_job, "review_required")
            db.commit()
            return "review_required"

    # Incidental findings gate
    critical_incidental = sum(1 for f in findings if f.severity == "critical")
    major_incidental = sum(1 for f in findings if f.severity == "major")

    if critical_incidental > 0 or major_incidental > 0:
        _set_status(inspection_job, "review_required")
        db.commit()
        return "review_required"

    # All checkpoints observed and passed, no blocking findings
    inspection_job.coverage_rate = 1.0
    inspection_job.has_unchecked_checkpoint = False
    _set_status(inspection_job, "pass")
    db.commit()
    return "pass"


def generate_final_report(
    db: Session,
    inspection_job: QCInspectionJob,
    final_result: str,
) -> QCFinalReport:
    cp_results = (
        db.query(QCCheckpointResult)
        .filter_by(inspection_job_id=inspection_job.id)
        .all()
    )
    findings = (
        db.query(QCIncidentalFinding)
        .filter_by(inspection_job_id=inspection_job.id)
        .all()
    )

    report_json = {
        "qc_result": final_result.upper(),
        "checkpoint_results": [
            {
                "code": r.checkpoint_code,
                "name": r.checkpoint_name,
                "result": r.result,
                "expected": r.expected_json,
                "observed": r.observed_json,
                "confidence": r.confidence_score,
                "failure_reason": r.failure_reason,
                "verification_status": r.verification_status,
            }
            for r in cp_results
        ],
        "incidental_findings": [
            {
                "finding_type": f.finding_type,
                "target_part": f.target_part,
                "severity": f.severity,
                "finding_text": f.finding_text,
                "confidence": f.confidence_score,
                "requires_human_review": f.requires_human_review,
            }
            for f in findings
        ],
    }

    report = QCFinalReport(
        inspection_job_id=inspection_job.id,
        report_status="final",
        final_result=final_result,
        report_json=report_json,
        generated_at=datetime.now(timezone.utc),
    )
    db.add(report)
    inspection_job.inspection_status = "final_report_generated"
    _audit(
        db,
        entity_type="qc_inspection_job",
        entity_id=inspection_job.id,
        event_type="inspection_finalized",
        event_json={"final_result": final_result},
    )
    db.commit()
    return report


def _update_job_counters(
    job: QCInspectionJob,
    cp_results: list[QCCheckpointResult],
) -> None:
    job.checkpoint_observed_count = sum(
        1 for r in cp_results if r.verification_status == "observed"
    )
    job.checkpoint_pass_count = sum(1 for r in cp_results if r.result == "pass")
    job.checkpoint_fail_count = sum(1 for r in cp_results if r.result == "fail")
    job.checkpoint_review_required_count = sum(
        1 for r in cp_results if r.result == "review_required"
    )
    job.has_unchecked_checkpoint = len(cp_results) < job.checkpoint_total
    job.coverage_rate = (
        len(cp_results) / job.checkpoint_total
        if job.checkpoint_total > 0
        else 0.0
    )


def _update_finding_counters(
    job: QCInspectionJob,
    findings: list[QCIncidentalFinding],
) -> None:
    job.incidental_finding_count += len(findings)
    job.major_incidental_finding_count += sum(
        1 for f in findings if f.severity == "major"
    )
    job.critical_incidental_finding_count += sum(
        1 for f in findings if f.severity == "critical"
    )


def _set_status(job: QCInspectionJob, status: str) -> None:
    job.inspection_status = status
    job.completed_at = datetime.now(timezone.utc)


def _audit(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    event_type: str,
    actor_id: Optional[str] = None,
    event_json: Optional[dict] = None,
) -> None:
    db.add(QCAuditEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor_id=actor_id,
        event_json=event_json or {},
    ))
