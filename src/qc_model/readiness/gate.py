"""Readiness-gated status transitions (PR 24 §5).

Extends the Training Pack status-transition logic so a transition into
``exam_ready`` or ``active`` first consults the readiness evaluator. This is a
**behavioral change**: transitions that previously depended only on structural
checks now also require confirmed QC knowledge completeness.

``on_trial`` is allowed when the pack is exam-ready but sample coverage is
insufficient; ``active`` additionally requires sufficient coverage.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from src.qc_model.readiness.evaluator import ReadinessResult, evaluate_readiness

# Target lifecycle states gated by readiness.
GATED_TARGETS = {"exam_ready", "active", "on_trial"}


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
    """Decide whether a training pack may transition into ``target_status``.

    Non-gated targets are always allowed (returns allowed=True). For gated
    targets, the readiness evaluator decides.
    """
    readiness = evaluate_readiness(db, training_pack_id, tenant_id)

    if target_status not in GATED_TARGETS:
        return TransitionDecision(True, target_status, "target_not_readiness_gated", readiness)

    if not readiness.pack_known:
        # Fail closed: unknown pack or a pack owned by a different tenant.
        return TransitionDecision(False, target_status, "unknown_or_cross_tenant_pack", readiness)

    if target_status == "exam_ready":
        allowed = readiness.exam_ready_allowed
        reason = "exam_ready_allowed" if allowed else "readiness_incomplete"
    elif target_status == "on_trial":
        allowed = readiness.on_trial_allowed
        reason = "on_trial_allowed" if allowed else "readiness_incomplete"
    else:  # active
        allowed = readiness.active_allowed
        if allowed:
            reason = "active_allowed"
        elif readiness.exam_ready_allowed and not readiness.active_allowed:
            reason = "insufficient_sample_coverage_use_on_trial"
        else:
            reason = "readiness_incomplete"

    return TransitionDecision(allowed, target_status, reason, readiness)
