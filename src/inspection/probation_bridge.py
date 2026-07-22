"""Bridge the Pad/web inspection flow into the Probation qualification loop.

PRD Authoring Extension §3.2: every job run while a standard revision is in
Probation must record the pair ``(ai_verdict, human_final_verdict, agreed)``
against real production jobs. The mechanism lives in
:mod:`src.qc_model.qualification.probation`; before this bridge it was only
wired to the L2 server-verdict path, so jobs finalized through the Pad/web
inspection-job flow never advanced a probation — a standard could run any
number of supervised jobs without ever becoming eligible for solo operation.

The AI verdict comes from the persisted vision suggestions
(``QCModelResult.raw_output.checkpoint_results``); the human final verdict is
the operator-reviewed final report. Per-point disagreements feed the
disagreement report.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from src.db.execution_models import QCFinalReport, QCInspectionJob, QCModelResult
from src.inspection.service import get_active_detection_points_for_job
from src.qc_model.qualification import probation as _probation

# Checkpoint suggestion values that cannot support an AI pass verdict —
# mirrors the no-guess finalize policy.
_NON_PASS = {"fail"}
_REVIEW = {"not_visible", "low_confidence", "missing", "unsupported", "uncertain"}


def _aggregate_ai_verdict(suggestions: list[dict[str, Any]]) -> str:
    results = [str(s.get("result", "")).lower() for s in suggestions]
    if not results:
        return "review_required"
    if any(r in _NON_PASS for r in results):
        return "fail"
    if any(r != "pass" for r in results):
        return "review_required"
    return "pass"


def record_probation_outcome(
    db: Session,
    job: QCInspectionJob,
    report: QCFinalReport,
    tenant_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Record this finalized job against its revision's probation, if any.

    Returns the probation recording summary, or None when the revision is not
    in an active probation / no AI suggestions exist / this job was already
    recorded (finalize is idempotent; re-recording is refused by job_ref).
    Never raises: probation bookkeeping must not undo a completed finalize.
    """
    tid = tenant_id or job.tenant_id
    probation = _probation.get_probation_for_revision(
        db, job.active_standard_revision_id, tid
    )
    if probation is None or probation.status != _probation.PROBATION_ACTIVE:
        return None

    model_result = (
        db.query(QCModelResult)
        .filter_by(job_id=job.id, tenant_id=tid)
        .order_by(QCModelResult.created_at.desc())
        .first()
    )
    raw = (model_result.raw_output or {}) if model_result is not None else {}
    suggestions = raw.get("checkpoint_results") or []
    if not suggestions:
        # No AI ran on this job — there is no (ai, human) pair to record.
        return None

    ai_verdict = _aggregate_ai_verdict(suggestions)
    human_verdict = report.overall_result

    points = get_active_detection_points_for_job(db, job.id, tenant_id=tid)
    code_by_id = {p.id: p.point_code for p in points}
    human_by_code: dict[str, str] = {}
    from src.db.execution_models import QCCheckpointResult

    for row in (
        db.query(QCCheckpointResult).filter_by(job_id=job.id, tenant_id=tid).all()
    ):
        code = code_by_id.get(row.detection_point_id)
        if code and getattr(row, "review_source", "model") == "operator":
            human_by_code[code] = row.result

    disagreements = []
    for item in suggestions:
        code = item.get("point_code")
        ai_point = str(item.get("result", "")).lower()
        human_point = human_by_code.get(code)
        if code and human_point is not None and human_point != ai_point:
            disagreements.append(
                {
                    "point_code": code,
                    "ai_verdict": ai_point,
                    "human_final_verdict": human_point,
                }
            )

    try:
        recorded = _probation.record_probation_job(
            db,
            probation_id=probation.id,
            ai_verdict=ai_verdict,
            human_final_verdict=human_verdict,
            tenant_id=tid,
            job_ref=job.id,
            point_disagreements=disagreements or None,
        )
    except (_probation.ProbationNotActive, _probation.InvalidProbationJob):
        # Paused/qualified race, or this job was already recorded.
        return None

    return {
        "probation_id": probation.id,
        "ai_verdict": ai_verdict,
        "human_final_verdict": human_verdict,
        "agreed": ai_verdict == human_verdict,
        "jobs_recorded": recorded["job"].sequence_no,
        "qualified_now": recorded.get("qualified_now", False),
        "point_disagreements": disagreements,
    }
