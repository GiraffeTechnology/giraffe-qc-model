"""Standard Probation workflow (PRD Authoring Extension §3).

A newly installed standard runs *real* production jobs under mandatory human
confirmation until it proves it can be trusted solo. This service owns the
probation counters, the qualification gate, the disagreement report, pause /
resume, and the "which edits reset progress" rule.

Key rules, straight from the PRD:

* Probation applies to a specific ``standard_revision_id`` (§3.2).
* Every job records ``(ai_verdict, human_final_verdict, agreed)`` against real
  work — never a synthetic test set (§3.2).
* Minimum sample size is **30 real jobs**. Even 100% agreement below 30 does not
  qualify (§3.2).
* From job 30 onward the agreement rate is checked; if not yet ≥90% it is
  rechecked every +10 jobs (40, 50, 60…) — no upper limit, no forced fallback
  (§3.2).
* At each check a disagreement report is produced (§3.2).
* The admin may pause probation at any time to edit the standard (§3.2).
* Editing ``expected_value`` or ``pass_criteria`` **resets** progress (a new
  revision, counter back to 0); editing ``description`` or ``regions`` does not
  (§3.4).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.qc_probation_models import (
    PROBATION_ACTIVE,
    PROBATION_PAUSED,
    PROBATION_QUALIFIED,
    QCProbation,
    QCProbationJob,
)

# ── Reset rule (§3.4) ─────────────────────────────────────────────────────────
# Editing what "correct" means invalidates prior agreement data; clarifying the
# description or adding spatial grounding does not change the judgment tested.
PROBATION_RESET_FIELDS = frozenset({
    "expected_value", "pass_criteria", "expected_features", "expected_features_json",
    "cv_config", "cv_config_json", "point_code", "method_hint", "severity",
})
PROBATION_PRESERVE_FIELDS = frozenset({"description", "regions", "regions_json"})

DEFAULT_MIN_SAMPLE_SIZE = 30
DEFAULT_AGREEMENT_THRESHOLD = 0.90
DEFAULT_RECHECK_INTERVAL = 10


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ProbationNotFound(ValueError):
    pass


class ProbationNotActive(ValueError):
    """Jobs can only be recorded while probation is active (not paused/qualified)."""


class InvalidProbationJob(ValueError):
    pass


class InvalidProbationState(ValueError):
    pass


# ── Gate snapshot ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ProbationGate:
    """Point-in-time evaluation of the qualification gate (§3.3)."""

    jobs_recorded: int
    agreements: int
    agreement_rate: float
    min_sample_size: int
    agreement_threshold: float
    recheck_interval: int
    min_sample_met: bool
    threshold_met: bool
    is_check_due: bool
    qualified: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "jobs_recorded": self.jobs_recorded,
            "agreements": self.agreements,
            "agreement_rate": self.agreement_rate,
            "min_sample_size": self.min_sample_size,
            "agreement_threshold": self.agreement_threshold,
            "recheck_interval": self.recheck_interval,
            "min_sample_met": self.min_sample_met,
            "threshold_met": self.threshold_met,
            "is_check_due": self.is_check_due,
            "qualified": self.qualified,
        }


def _normalize_verdict(value: str) -> str:
    return (value or "").strip().lower()


# ── Lifecycle ─────────────────────────────────────────────────────────────────


def start_probation(
    db: Session,
    standard_revision_id: str,
    tenant_id: str = "default",
    sku_id: Optional[str] = None,
    min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE,
    agreement_threshold: float = DEFAULT_AGREEMENT_THRESHOLD,
    recheck_interval: int = DEFAULT_RECHECK_INTERVAL,
) -> QCProbation:
    """Get-or-create the probation record for a standard revision.

    Idempotent per ``(tenant_id, standard_revision_id)`` — a revision only ever
    has one probation. A fresh revision (created by a reset edit, §3.4) is a new
    id, so it gets its own record with the counter at 0.
    """
    if min_sample_size < 1:
        raise InvalidProbationState("min_sample_size must be >= 1")
    if not (0.0 < agreement_threshold <= 1.0):
        raise InvalidProbationState("agreement_threshold must be in (0, 1]")
    if recheck_interval < 1:
        raise InvalidProbationState("recheck_interval must be >= 1")

    existing = get_probation_for_revision(db, standard_revision_id, tenant_id)
    if existing is not None:
        return existing

    probation = QCProbation(
        id=_uid(),
        tenant_id=tenant_id,
        sku_id=sku_id,
        standard_revision_id=standard_revision_id,
        status=PROBATION_ACTIVE,
        min_sample_size=min_sample_size,
        agreement_threshold=agreement_threshold,
        recheck_interval=recheck_interval,
    )
    db.add(probation)
    db.commit()
    db.refresh(probation)
    return probation


def get_probation(db: Session, probation_id: str, tenant_id: str = "default") -> QCProbation:
    p = db.query(QCProbation).filter_by(id=probation_id, tenant_id=tenant_id).first()
    if p is None:
        raise ProbationNotFound(f"probation {probation_id!r} not found")
    return p


def get_probation_for_revision(
    db: Session, standard_revision_id: str, tenant_id: str = "default"
) -> Optional[QCProbation]:
    return (
        db.query(QCProbation)
        .filter_by(standard_revision_id=standard_revision_id, tenant_id=tenant_id)
        .first()
    )


# ── Gate evaluation ───────────────────────────────────────────────────────────


def evaluate_gate(probation: QCProbation) -> ProbationGate:
    """Evaluate the qualification gate for a probation's current counters.

    Agreement rate is only *meaningful* once the minimum sample size is met, so
    ``qualified`` is False below it regardless of the rate (§3.2).
    """
    n = probation.jobs_recorded
    agrees = probation.agreements
    rate = (agrees / n) if n else 0.0
    min_met = n >= probation.min_sample_size
    threshold_met = rate >= probation.agreement_threshold
    # Checks happen at the minimum sample size, then every +recheck_interval
    # jobs: 30, 40, 50, … (§3.2).
    is_check_due = min_met and ((n - probation.min_sample_size) % probation.recheck_interval == 0)
    qualified = min_met and threshold_met
    return ProbationGate(
        jobs_recorded=n,
        agreements=agrees,
        agreement_rate=rate,
        min_sample_size=probation.min_sample_size,
        agreement_threshold=probation.agreement_threshold,
        recheck_interval=probation.recheck_interval,
        min_sample_met=min_met,
        threshold_met=threshold_met,
        is_check_due=is_check_due,
        qualified=qualified,
    )


# ── Record a real job ─────────────────────────────────────────────────────────


def record_probation_job(
    db: Session,
    probation_id: str,
    ai_verdict: str,
    human_final_verdict: str,
    tenant_id: str = "default",
    job_ref: Optional[str] = None,
    point_disagreements: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Record one real production job's ``(ai, human)`` verdict pair (§3.2).

    Returns ``{"job", "gate", "qualified_now", "check_due"}``. When a check is
    due (job 30, 40, …) and the threshold is met, the probation auto-transitions
    to ``qualified``.

    ``point_disagreements`` is an optional list of
    ``{"point_code", "ai_verdict", "human_final_verdict"}`` for the detection
    points that diverged on this job, feeding the disagreement report.
    """
    probation = get_probation(db, probation_id, tenant_id)
    if probation.status == PROBATION_QUALIFIED:
        raise ProbationNotActive("probation is already qualified; standard runs solo")
    if probation.status == PROBATION_PAUSED:
        raise ProbationNotActive("probation is paused; resume it before recording jobs")

    ai = _normalize_verdict(ai_verdict)
    human = _normalize_verdict(human_final_verdict)
    if not ai or not human:
        raise InvalidProbationJob("both ai_verdict and human_final_verdict are required")

    if job_ref:
        dup = (
            db.query(QCProbationJob)
            .filter_by(tenant_id=tenant_id, probation_id=probation.id, job_ref=job_ref)
            .first()
        )
        if dup is not None:
            raise InvalidProbationJob(f"job_ref {job_ref!r} already recorded for this probation")

    agreed = ai == human
    clean_points = _clean_point_disagreements(point_disagreements)

    probation.jobs_recorded += 1
    if agreed:
        probation.agreements += 1

    job = QCProbationJob(
        id=_uid(),
        tenant_id=tenant_id,
        probation_id=probation.id,
        standard_revision_id=probation.standard_revision_id,
        job_ref=job_ref,
        ai_verdict=ai,
        human_final_verdict=human,
        agreed=agreed,
        point_disagreements_json=clean_points,
        sequence_no=probation.jobs_recorded,
    )
    db.add(job)
    db.flush()

    gate = evaluate_gate(probation)
    qualified_now = False
    # Qualify only at a scheduled check (30, 40, …) when the threshold holds.
    if gate.is_check_due and gate.threshold_met and probation.status != PROBATION_QUALIFIED:
        probation.status = PROBATION_QUALIFIED
        probation.qualified_at = _now()
        qualified_now = True

    db.commit()
    db.refresh(probation)
    db.refresh(job)
    return {
        "job": job,
        "gate": evaluate_gate(probation),
        "qualified_now": qualified_now,
        "check_due": gate.is_check_due,
    }


def _clean_point_disagreements(
    point_disagreements: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, str]]:
    if not point_disagreements:
        return []
    clean: List[Dict[str, str]] = []
    for i, pd in enumerate(point_disagreements):
        if not isinstance(pd, dict):
            raise InvalidProbationJob(f"point_disagreements[{i}] must be an object")
        code = pd.get("point_code")
        if not code:
            raise InvalidProbationJob(f"point_disagreements[{i}].point_code is required")
        clean.append({
            "point_code": str(code),
            "ai_verdict": _normalize_verdict(str(pd.get("ai_verdict", ""))),
            "human_final_verdict": _normalize_verdict(str(pd.get("human_final_verdict", ""))),
        })
    return clean


# ── Disagreement report (§3.2) ────────────────────────────────────────────────


def disagreement_report(
    db: Session, probation_id: str, tenant_id: str = "default"
) -> Dict[str, Any]:
    """Report which detection point(s) diverged: AI said vs. human decided.

    Reuses the caller's existing conversational display component — this returns
    plain structured data, no new UI (§3.2).
    """
    probation = get_probation(db, probation_id, tenant_id)
    jobs = (
        db.query(QCProbationJob)
        .filter_by(probation_id=probation.id, tenant_id=tenant_id)
        .order_by(QCProbationJob.sequence_no.asc())
        .all()
    )
    gate = evaluate_gate(probation)

    job_disagreements: List[Dict[str, Any]] = []
    by_point: Dict[str, Dict[str, Any]] = {}
    for job in jobs:
        if job.agreed and not (job.point_disagreements_json or []):
            continue
        job_disagreements.append({
            "job_ref": job.job_ref,
            "sequence_no": job.sequence_no,
            "ai_verdict": job.ai_verdict,
            "human_final_verdict": job.human_final_verdict,
            "agreed": job.agreed,
            "points": job.point_disagreements_json or [],
        })
        for pd in job.point_disagreements_json or []:
            code = pd.get("point_code", "unknown")
            entry = by_point.setdefault(
                code, {"point_code": code, "disagreement_count": 0, "examples": []}
            )
            entry["disagreement_count"] += 1
            if len(entry["examples"]) < 10:
                entry["examples"].append({
                    "job_ref": job.job_ref,
                    "sequence_no": job.sequence_no,
                    "ai_verdict": pd.get("ai_verdict"),
                    "human_final_verdict": pd.get("human_final_verdict"),
                })

    return {
        "probation_id": probation.id,
        "standard_revision_id": probation.standard_revision_id,
        "status": probation.status,
        "gate": gate.to_dict(),
        "disagreements": len(job_disagreements),
        "detection_points": sorted(
            by_point.values(), key=lambda e: e["disagreement_count"], reverse=True
        ),
        "jobs": job_disagreements,
    }


# ── Pause / resume (§3.2) ─────────────────────────────────────────────────────


def pause_probation(db: Session, probation_id: str, tenant_id: str = "default") -> QCProbation:
    """Admin pauses probation at any time to edit the standard in Studio."""
    probation = get_probation(db, probation_id, tenant_id)
    if probation.status == PROBATION_QUALIFIED:
        raise InvalidProbationState("cannot pause a qualified standard")
    if probation.status == PROBATION_PAUSED:
        return probation
    probation.status = PROBATION_PAUSED
    probation.paused_at = _now()
    db.commit()
    db.refresh(probation)
    return probation


def resume_probation(db: Session, probation_id: str, tenant_id: str = "default") -> QCProbation:
    probation = get_probation(db, probation_id, tenant_id)
    if probation.status == PROBATION_QUALIFIED:
        raise InvalidProbationState("cannot resume a qualified standard")
    probation.status = PROBATION_ACTIVE
    probation.paused_at = None
    db.commit()
    db.refresh(probation)
    return probation


# ── Reset rule for edits (§3.4) ───────────────────────────────────────────────


def edit_resets_probation(changed_fields: List[str] | set[str]) -> bool:
    """True if editing any of ``changed_fields`` invalidates probation progress.

    Editing ``expected_value`` / ``pass_criteria`` changes what "correct" means
    → reset. Editing ``description`` / ``regions`` does not → preserved (§3.4).
    """
    return bool(set(changed_fields) & PROBATION_RESET_FIELDS)


__all__ = [
    "PROBATION_ACTIVE",
    "PROBATION_PAUSED",
    "PROBATION_QUALIFIED",
    "PROBATION_RESET_FIELDS",
    "PROBATION_PRESERVE_FIELDS",
    "ProbationGate",
    "ProbationNotFound",
    "ProbationNotActive",
    "InvalidProbationJob",
    "InvalidProbationState",
    "start_probation",
    "get_probation",
    "get_probation_for_revision",
    "evaluate_gate",
    "record_probation_job",
    "disagreement_report",
    "pause_probation",
    "resume_probation",
    "edit_resets_probation",
]
