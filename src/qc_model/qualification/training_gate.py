"""Rolling-window training gate for the Digital QC Studio (PRD §9.5-9.8).

A standard revision may only be published once its reviewed training
judgments satisfy either:

* the most recent 29 reviewed judgments are ALL correct, or
* the most recent 30 reviewed judgments include at least 29 correct
  (i.e. at most one incorrect),

AND the qualifying window contains zero false passes (an unqualified
sample the model called "pass" — never averaged away by an otherwise
strong window), AND the window covers at least one qualified and one
unqualified ground-truth sample (PRD §9.7 item 6).

Only admin-reviewed judgments (``status == "reviewed"``) count toward
either window — an ``awaiting_admin_review`` record is not a training
sample (PRD §9.7 item 1): "未裁决记录不计入有效训练次数."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from src.db.training_models import QCTrainingJudgment

WINDOW_STRICT = 29
WINDOW_LENIENT = 30
WINDOW_LENIENT_MIN_CORRECT = 29


@dataclass(frozen=True)
class TrainingGateStatus:
    total_reviewed: int
    recent_29_correct: "int | None"
    recent_30_correct: "int | None"
    recent_30_false_pass_count: int
    recent_30_covers_both_labels: bool
    qualified: bool
    reason: str
    per_checkpoint_accuracy: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_reviewed": self.total_reviewed,
            "recent_29_correct": self.recent_29_correct,
            "recent_30_correct": self.recent_30_correct,
            "recent_30_false_pass_count": self.recent_30_false_pass_count,
            "recent_30_covers_both_labels": self.recent_30_covers_both_labels,
            "qualified": self.qualified,
            "reason": self.reason,
            "per_checkpoint_accuracy": self.per_checkpoint_accuracy,
        }


def _per_checkpoint_accuracy(records: list[QCTrainingJudgment]) -> dict[str, dict[str, Any]]:
    """Informational per-checkpoint accuracy across all reviewed records.

    Not itself a gate input (the gate is the overall admin-decision rolling
    window below), but PRD §9.5 item 7 requires it be visible to the admin.

    The admin reviews each *sample* as a whole (correct/incorrect), not
    each checkpoint individually, so per-checkpoint correctness is derived:
    a "correct" decision counts every checkpoint in that sample as correct
    (the admin confirmed the model's full verdict, including its localized
    findings); an "incorrect" decision counts only the checkpoint named in
    ``correction_json.point_code`` as wrong and every other checkpoint in
    that sample as correct, since the correction form identifies where the
    error was rather than re-litigating every point.
    """
    totals: dict[str, list[int]] = {}
    for record in records:
        wrong_point = (record.correction_json or {}).get("point_code") if record.admin_decision == "incorrect" else None
        for item in record.model_checkpoint_results_json or []:
            code = item.get("point_code")
            if not code:
                continue
            counts = totals.setdefault(code, [0, 0])
            counts[0] += 1
            if code != wrong_point:
                counts[1] += 1
    return {
        code: {"total": total, "correct": correct, "accuracy": (correct / total if total else 0.0)}
        for code, (total, correct) in totals.items()
    }


def _window_qualifies(window: list[QCTrainingJudgment], min_correct: int) -> tuple[bool, str]:
    correct = sum(1 for r in window if r.admin_decision == "correct")
    if correct < min_correct:
        return False, f"correct_{correct}_below_{min_correct}"
    false_passes = sum(1 for r in window if r.is_false_pass)
    if false_passes:
        return False, f"false_pass_in_window:{false_passes}"
    labels = {r.ground_truth_label for r in window}
    if not ({"qualified", "unqualified"} <= labels):
        return False, "window_missing_a_ground_truth_label"
    return True, "ok"


def evaluate_training_gate(
    db: Session, *, tenant_id: str, sku_id: str, standard_revision_id: str,
) -> TrainingGateStatus:
    """Compute the rolling-window publish gate for one standard revision."""
    records = (
        db.query(QCTrainingJudgment)
        .filter_by(
            tenant_id=tenant_id, sku_id=sku_id,
            standard_revision_id=standard_revision_id, status="reviewed",
        )
        .order_by(QCTrainingJudgment.reviewed_at.asc(), QCTrainingJudgment.created_at.asc())
        .all()
    )
    total = len(records)
    per_checkpoint = _per_checkpoint_accuracy(records)

    window29 = records[-WINDOW_STRICT:] if total >= WINDOW_STRICT else None
    window30 = records[-WINDOW_LENIENT:] if total >= WINDOW_LENIENT else None

    ok29, reason29 = _window_qualifies(window29, WINDOW_STRICT) if window29 else (False, "insufficient_samples_29")
    ok30, reason30 = (
        _window_qualifies(window30, WINDOW_LENIENT_MIN_CORRECT) if window30 else (False, "insufficient_samples_30")
    )

    qualified = ok29 or ok30
    if qualified:
        reason = "qualified_29_of_29" if ok29 else "qualified_29_of_30"
    else:
        reason = reason30 if window30 is not None else reason29

    recent_29_correct = sum(1 for r in window29 if r.admin_decision == "correct") if window29 else None
    recent_30_correct = sum(1 for r in window30 if r.admin_decision == "correct") if window30 else None
    false_pass_30 = sum(1 for r in window30 if r.is_false_pass) if window30 else 0
    covers_both_30 = (
        {"qualified", "unqualified"} <= {r.ground_truth_label for r in window30} if window30 else False
    )

    return TrainingGateStatus(
        total_reviewed=total,
        recent_29_correct=recent_29_correct,
        recent_30_correct=recent_30_correct,
        recent_30_false_pass_count=false_pass_30,
        recent_30_covers_both_labels=covers_both_30,
        qualified=qualified,
        reason=reason,
        per_checkpoint_accuracy=per_checkpoint,
    )


__all__ = [
    "WINDOW_STRICT",
    "WINDOW_LENIENT",
    "WINDOW_LENIENT_MIN_CORRECT",
    "TrainingGateStatus",
    "evaluate_training_gate",
]
