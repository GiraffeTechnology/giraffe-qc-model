"""Server verdict recompute service (§9) — receiving/recompute/display side.

Persists Pad submissions, recomputes the authoritative verdict via the pure
:mod:`src.qc_model.verdict.recompute` core, and stores the result for the admin
Results page. Does not implement Pad-side submission (S6 owns that).

The standard-revision spec is resolved from the revision the Pad *used*
(``standard_revision_id``), never the latest revision. An unrecognised revision
resolves to ``None`` → fail closed.
"""
from __future__ import annotations

import uuid
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import _utcnow
from src.db.qc_verdict_models import (
    QCPadSubmission,
    QCServerVerdict,
    QCSubmittedCheckpoint,
)
from src.qc_model.qualification import probation as _probation
from src.qc_model.verdict.recompute import (
    PadSubmission,
    ServerVerdict,
    StandardRevisionSpec,
    SubmittedCheckpoint,
    recompute_verdict,
)

_VALID_HUMAN_DECISIONS = {"pass", "fail", "reject", "review", "escalate"}


class SubmissionNotFound(Exception):
    pass


def _uid() -> str:
    return uuid.uuid4().hex


def resolve_spec(
    db: Session,
    *,
    tenant_id: str,
    standard_revision_id: str,
    used_bundle_version: str,
    expected_bundle_version: Optional[str] = None,
) -> Optional[StandardRevisionSpec]:
    """Build the authoritative spec for the revision the Pad used.

    Returns ``None`` when the revision is unknown to this tenant → the caller
    (and recompute) fails closed. Required checkpoints are the *active* detection
    points of that exact revision — critical ones are tracked separately.

    ``expected_bundle_version`` lets a deployment that tracks the
    revision→bundle mapping enforce the §9.5 mismatch check; when omitted we
    treat the used version as authoritative so no false mismatch is raised.
    """
    # Imported lazily so this module does not hard-couple to the SKU tables at
    # import time (keeps the pure recompute path importable on its own).
    from src.db.sku_models import QCDetectionPoint, QCSkuStandardRevision

    revision = db.scalar(
        select(QCSkuStandardRevision).where(
            QCSkuStandardRevision.id == standard_revision_id,
            QCSkuStandardRevision.tenant_id == tenant_id,
        )
    )
    if revision is None:
        return None

    points = db.scalars(
        select(QCDetectionPoint).where(
            QCDetectionPoint.standard_revision_id == standard_revision_id,
            QCDetectionPoint.tenant_id == tenant_id,
            QCDetectionPoint.is_active.is_(True),
        )
    ).all()
    required = frozenset(p.point_code for p in points)
    critical = frozenset(p.point_code for p in points if p.severity == "critical")

    return StandardRevisionSpec(
        revision_id=standard_revision_id,
        bundle_version=expected_bundle_version if expected_bundle_version is not None else used_bundle_version,
        required_checkpoint_ids=required,
        critical_checkpoint_ids=critical,
        known=True,
    )


def ingest_submission(
    db: Session,
    *,
    tenant_id: str,
    job_ref: str,
    standard_revision_id: str,
    bundle_version: str,
    pad_overall_result: str,
    checkpoints: Iterable[tuple[str, str]],
    workstation_id: Optional[str] = None,
    expected_bundle_version: Optional[str] = None,
    raw: Optional[dict] = None,
) -> tuple[QCPadSubmission, QCServerVerdict, ServerVerdict]:
    """Persist a Pad submission and its server-recomputed verdict."""
    checkpoint_list = list(checkpoints)

    submission = QCPadSubmission(
        id=_uid(),
        tenant_id=tenant_id,
        job_ref=job_ref,
        standard_revision_id=standard_revision_id,
        bundle_version=bundle_version,
        workstation_id=workstation_id,
        pad_overall_result=pad_overall_result,
        raw_json=raw,
    )
    db.add(submission)
    for cid, res in checkpoint_list:
        db.add(
            QCSubmittedCheckpoint(
                id=_uid(),
                submission_id=submission.id,
                tenant_id=tenant_id,
                checkpoint_id=cid,
                result=res,
            )
        )

    spec = resolve_spec(
        db,
        tenant_id=tenant_id,
        standard_revision_id=standard_revision_id,
        used_bundle_version=bundle_version,
        expected_bundle_version=expected_bundle_version,
    )
    pad_submission = PadSubmission(
        job_ref=job_ref,
        standard_revision_id=standard_revision_id,
        bundle_version=bundle_version,
        pad_overall_result=pad_overall_result,
        checkpoints=tuple(SubmittedCheckpoint(cid, res) for cid, res in checkpoint_list),
    )
    verdict = recompute_verdict(pad_submission, spec)

    verdict_model = QCServerVerdict(
        id=_uid(),
        submission_id=submission.id,
        tenant_id=tenant_id,
        server_overall_result=verdict.server_overall_result,
        pad_overall_result=verdict.pad_overall_result,
        agrees=verdict.agrees,
        review_required=verdict.review_required,
        rule_applied=verdict.rule_applied,
        standard_revision_id=standard_revision_id,
        bundle_version=bundle_version,
        missing_checkpoints_json=verdict.missing_checkpoints,
        failing_checkpoints_json=verdict.failing_checkpoints,
        warnings_json=verdict.warnings,
        differences_json=verdict.differences,
    )
    db.add(verdict_model)
    db.commit()
    db.refresh(submission)
    db.refresh(verdict_model)
    return submission, verdict_model, verdict


def list_results(db: Session, tenant_id: str) -> list[QCServerVerdict]:
    return list(
        db.scalars(
            select(QCServerVerdict)
            .where(QCServerVerdict.tenant_id == tenant_id)
            .order_by(QCServerVerdict.recomputed_at.desc())
        )
    )


def get_result(db: Session, tenant_id: str, submission_id: str) -> QCServerVerdict:
    verdict = db.scalar(
        select(QCServerVerdict).where(
            QCServerVerdict.submission_id == submission_id,
            QCServerVerdict.tenant_id == tenant_id,
        )
    )
    if verdict is None:
        raise SubmissionNotFound(submission_id)
    return verdict


def record_human_decision(
    db: Session,
    *,
    tenant_id: str,
    submission_id: str,
    decision: str,
    decided_by: str,
    comment: str = "",
) -> QCServerVerdict:
    """Record the human final decision. Does not mutate the server verdict."""
    if decision not in _VALID_HUMAN_DECISIONS:
        raise ValueError(f"invalid_decision:{decision}")
    verdict = get_result(db, tenant_id, submission_id)
    verdict.human_final_decision = decision
    verdict.human_decided_by = decided_by
    verdict.human_decision_comment = comment or None
    verdict.human_decided_at = _utcnow()
    db.commit()
    db.refresh(verdict)
    _maybe_record_probation_job(db, verdict, tenant_id)
    return verdict


def _maybe_record_probation_job(db: Session, verdict: QCServerVerdict, tenant_id: str) -> None:
    """Feed this human final decision into Standard Probation (§3.2) when the
    standard revision it was judged against is currently on probation.

    This is a real, mandatory-human-confirmation *result*, not a synthetic test
    -- exactly the evidence probation.py requires (never a fabricated agree/
    disagree pair). A no-op when the revision was never published through the
    Studio publish flow (no probation record) or is paused/qualified: this
    hook must never block a human's decision from being recorded.

    Per-detection-point disagreement data is intentionally left unset here --
    this flow only captures a single overall human final decision, not a
    per-checkpoint human verdict, so there is no real per-point AI-vs-human
    comparison to record without fabricating one.
    """
    probation = _probation.get_probation_for_revision(db, verdict.standard_revision_id, tenant_id)
    if probation is None or probation.status != _probation.PROBATION_ACTIVE:
        return
    submission = db.get(QCPadSubmission, verdict.submission_id)
    try:
        _probation.record_probation_job(
            db,
            probation.id,
            ai_verdict=verdict.server_overall_result,
            human_final_verdict=verdict.human_final_decision,
            tenant_id=tenant_id,
            job_ref=submission.job_ref if submission else None,
        )
    except _probation.InvalidProbationJob:
        # Same job_ref already recorded (e.g. the final decision was amended
        # and resubmitted) -- probation only counts a job once.
        pass
