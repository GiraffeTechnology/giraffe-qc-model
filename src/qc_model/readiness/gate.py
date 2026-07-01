"""Readiness-gated status transitions (PR 24 + Production Readiness §4).

A transition into ``exam_ready`` / ``on_trial`` / ``production_assisted`` (L2) /
``active`` / ``controlled_active`` (L3) first consults the readiness evaluator.

Mode mapping (PRD §2):
- ``on_trial``            → L1/L2 trial gate (knowledge-complete / exam_ready).
- ``production_assisted`` → L2, requires approved/applied visual memory,
  production-eligible provider, coverage, and pseudo/capture closure.
- ``active`` / ``controlled_active`` → L3, additionally requires a qualification
  report (fails closed until qualification exists).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.qc_model.readiness.evaluator import (
    TARGET_CONTROLLED_ACTIVE,
    TARGET_EXAM_READY,
    TARGET_PRODUCTION_ASSISTED,
    ReadinessResult,
    evaluate_readiness,
)

GATED_TARGETS = {
    "exam_ready", "on_trial", "production_assisted", "active", "controlled_active",
}

_TARGET_MODE = {
    "production_assisted": TARGET_PRODUCTION_ASSISTED,
    "active": TARGET_CONTROLLED_ACTIVE,
    "controlled_active": TARGET_CONTROLLED_ACTIVE,
}


@dataclass
class TransitionDecision:
    allowed: bool
    target_status: str
    reason: str
    readiness: ReadinessResult


def gate_transition(
    db: Session,
    training_pack_id: str,
    target_status: str,
    tenant_id: str = "default",
) -> TransitionDecision:
    """Decide whether a training pack may transition into ``target_status``."""
    mode = _TARGET_MODE.get(target_status, TARGET_EXAM_READY)
    readiness = evaluate_readiness(db, training_pack_id, tenant_id, target_mode=mode)

    if target_status not in GATED_TARGETS:
        return TransitionDecision(True, target_status, "target_not_readiness_gated", readiness)

    if not readiness.pack_known:
        return TransitionDecision(False, target_status, "unknown_or_cross_tenant_pack", readiness)

    if target_status in ("exam_ready", "on_trial"):
        allowed = readiness.exam_ready_allowed
        reason = "exam_ready_allowed" if allowed else "readiness_incomplete"
    elif target_status == "production_assisted":
        allowed = readiness.production_assisted_allowed
        if allowed:
            reason = "production_assisted_allowed"
        elif readiness.exam_ready_allowed:
            reason = "production_prerequisites_incomplete"
        else:
            reason = "readiness_incomplete"
    else:  # active / controlled_active (L3)
        allowed = readiness.controlled_active_allowed
        if allowed:
            reason = "controlled_active_allowed"
        elif readiness.production_assisted_allowed:
            reason = "qualification_required_for_controlled_active"
        else:
            reason = "readiness_incomplete"

    return TransitionDecision(allowed, target_status, reason, readiness)
