"""Digital inspector lifecycle state machine + guardrails (PRD §11).

Lifecycle:
    draft → training_pack_pending → learning → exam_ready
          → exam_failed | exam_passed → on_trial → active
          → suspended → retired

This module owns the rules for *what an inspector in a given state is allowed
to do*. The runner consults :func:`can_inspect` before any provider call and
:func:`apply_lifecycle_policy` after finalization.
"""
from __future__ import annotations

from src.qc_model.schemas.digital_inspector import InspectorStatus
from src.qc_model.schemas.inspection import InspectionResult

# Allowed forward/!backward transitions. Used to validate transition requests.
_ALLOWED_TRANSITIONS: dict[InspectorStatus, set[InspectorStatus]] = {
    InspectorStatus.DRAFT: {InspectorStatus.TRAINING_PACK_PENDING, InspectorStatus.RETIRED},
    InspectorStatus.TRAINING_PACK_PENDING: {
        InspectorStatus.LEARNING,
        InspectorStatus.DRAFT,
        InspectorStatus.RETIRED,
    },
    InspectorStatus.LEARNING: {
        InspectorStatus.EXAM_READY,
        InspectorStatus.TRAINING_PACK_PENDING,
        InspectorStatus.RETIRED,
    },
    InspectorStatus.EXAM_READY: {
        InspectorStatus.EXAM_PASSED,
        InspectorStatus.EXAM_FAILED,
        InspectorStatus.RETIRED,
    },
    InspectorStatus.EXAM_FAILED: {
        InspectorStatus.LEARNING,
        InspectorStatus.EXAM_READY,
        InspectorStatus.RETIRED,
    },
    InspectorStatus.EXAM_PASSED: {
        InspectorStatus.ON_TRIAL,
        InspectorStatus.RETIRED,
    },
    InspectorStatus.ON_TRIAL: {
        InspectorStatus.ACTIVE,
        InspectorStatus.SUSPENDED,
        InspectorStatus.RETIRED,
    },
    InspectorStatus.ACTIVE: {
        InspectorStatus.SUSPENDED,
        InspectorStatus.ON_TRIAL,
        InspectorStatus.RETIRED,
    },
    InspectorStatus.SUSPENDED: {
        InspectorStatus.ON_TRIAL,
        InspectorStatus.LEARNING,
        InspectorStatus.EXAM_READY,
        InspectorStatus.RETIRED,
    },
    InspectorStatus.RETIRED: set(),
}

# States in which the inspector may run inspection at all.
_INSPECTABLE = {
    InspectorStatus.ON_TRIAL,
    InspectorStatus.ACTIVE,
    InspectorStatus.SUSPENDED,  # may only emit review_required
}


def _as_status(status) -> InspectorStatus:
    return status if isinstance(status, InspectorStatus) else InspectorStatus(status)


def can_transition(current, target) -> bool:
    return _as_status(target) in _ALLOWED_TRANSITIONS.get(_as_status(current), set())


def can_inspect(status) -> bool:
    """True if the inspector may run inspection in this state."""
    return _as_status(status) in _INSPECTABLE


def requires_mandatory_human_review(status) -> bool:
    """on_trial and suspended require mandatory human review of any output."""
    return _as_status(status) in (InspectorStatus.ON_TRIAL, InspectorStatus.SUSPENDED)


def not_inspectable_reason(status) -> str:
    return f"inspector_state_{_as_status(status).value}_cannot_inspect"


def apply_lifecycle_policy(status, result: InspectionResult) -> InspectionResult:
    """Apply state-specific output policy to a finalized result (PRD §11.1).

    - ``suspended``: may only ever issue ``review_required``.
    - ``on_trial``: keep the AI suggestion but force mandatory human review.
    - ``active``: pass/fail/review_required as finalized.
    """
    state = _as_status(status)

    if state == InspectorStatus.SUSPENDED:
        forced = result.model_copy(
            update={
                "overall_result": "review_required",
                "requires_human_review": True,
                "finalization_rule_applied": (
                    (result.finalization_rule_applied + "; " if result.finalization_rule_applied else "")
                    + "inspector_suspended_review_required_only"
                ),
            }
        )
        forced.checkpoint_results = [
            cp.model_copy(update={"result": "review_required", "requires_human_review": True})
            for cp in result.checkpoint_results
        ]
        return forced

    if state == InspectorStatus.ON_TRIAL:
        trial = result.model_copy(
            update={
                "requires_human_review": True,
                "finalization_rule_applied": (
                    (result.finalization_rule_applied + "; " if result.finalization_rule_applied else "")
                    + "on_trial_mandatory_human_review"
                ),
            }
        )
        trial.checkpoint_results = [
            cp.model_copy(update={"requires_human_review": True})
            for cp in result.checkpoint_results
        ]
        return trial

    return result
