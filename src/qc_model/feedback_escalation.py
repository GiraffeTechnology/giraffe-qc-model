"""Human feedback handling + false-pass P0 escalation (PRD §18.3).

Any ``false_pass`` is a P0 incident. The system must:
    1. Mark the inspection as a P0 incident.
    2. Add the sample to the misjudgment library.
    3. Suspend the inspector (or downgrade an on_trial inspector).
    4. Require supervisor review.
    5. Require a Training Pack / prompt update.
    6. Require requalification before returning to active.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.qc_model.schemas.digital_inspector import DigitalInspector, InspectorStatus
from src.qc_model.schemas.feedback import HumanFeedback


@dataclass
class MisjudgmentCase:
    inspection_id: str
    feedback_id: str
    misjudgment_type: str
    priority: str  # "P0" for false_pass
    eligible_for_training_pack: bool


@dataclass
class EscalationResult:
    """Outcome of processing one piece of human feedback."""

    inspector: DigitalInspector
    is_p0_incident: bool = False
    misjudgment_case: MisjudgmentCase | None = None
    requires_supervisor_review: bool = False
    requires_training_pack_update: bool = False
    requires_requalification: bool = False
    actions: list[str] = field(default_factory=list)


def process_human_feedback(
    feedback: HumanFeedback,
    inspector: DigitalInspector,
) -> EscalationResult:
    """Process feedback and return the (possibly downgraded) inspector.

    The inspector is returned as a *new* object; the input is not mutated.
    """
    if not feedback.is_false_pass():
        # Non-false-pass feedback is recorded but does not trigger P0 actions.
        return EscalationResult(
            inspector=inspector,
            actions=["feedback_recorded"],
        )

    # ── False pass: P0 escalation ─────────────────────────────────────────
    case = MisjudgmentCase(
        inspection_id=feedback.inspection_id,
        feedback_id=feedback.feedback_id,
        misjudgment_type="false_pass",
        priority="P0",
        eligible_for_training_pack=True,
    )

    # Suspend an active inspector; downgrade an on_trial inspector to suspended
    # as well (it can no longer be trusted until requalification).
    new_status = InspectorStatus.SUSPENDED
    downgraded = inspector.model_copy(
        update={
            "status": new_status,
            "requires_requalification": True,
        }
    )

    return EscalationResult(
        inspector=downgraded,
        is_p0_incident=True,
        misjudgment_case=case,
        requires_supervisor_review=True,
        requires_training_pack_update=True,
        requires_requalification=True,
        actions=[
            "marked_p0_incident",
            "added_to_misjudgment_library",
            "inspector_suspended",
            "supervisor_review_required",
            "training_pack_update_required",
            "requalification_required",
        ],
    )
