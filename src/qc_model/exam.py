"""Qualification exam skeleton (PRD §13).

Phase 1 implements the exam metric data model + scoring + thresholds. It does
NOT certify real qwen3.5-vl accuracy. ``false_pass_count == 0`` is mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.qc_model.schemas.digital_inspector import InspectorStatus


@dataclass
class ExamMetrics:
    """Metric fields prepared for qualification scoring (PRD §13.2)."""

    false_pass_count: int = 0
    false_fail_count: int = 0
    critical_defect_recall: float = 0.0
    overall_accuracy: float = 0.0
    checkpoint_accuracy: float = 0.0
    review_required_precision: float = 0.0
    evidence_acceptance_rate: float = 0.0
    same_image_repeat_stability: float = 0.0
    capture_artifact_handling_rate: float = 0.0


# Initial target thresholds (PRD §13.3).
THRESHOLDS = {
    "false_pass_count": 0,  # mandatory, exact
    "critical_defect_recall": 0.95,
    "overall_accuracy": 0.90,
    "checkpoint_accuracy": 0.90,
    "evidence_acceptance_rate": 0.90,
    "same_image_repeat_stability": 0.95,
}


@dataclass
class ExamOutcome:
    passed: bool
    failures: list[str] = field(default_factory=list)
    # The lifecycle status the inspector should move to as a result.
    resulting_status: InspectorStatus = InspectorStatus.EXAM_FAILED


def score_exam(metrics: ExamMetrics, enough_samples: bool = True) -> ExamOutcome:
    """Score exam metrics against thresholds.

    ``false_pass_count == 0`` is mandatory. If not enough samples exist the
    inspector may only enter ``on_trial`` (never ``active``) — modelled by a
    pass that resolves to exam_passed but flagged via ``enough_samples``.
    """
    failures: list[str] = []

    if metrics.false_pass_count != THRESHOLDS["false_pass_count"]:
        failures.append("false_pass_count_must_be_zero")
    if metrics.critical_defect_recall < THRESHOLDS["critical_defect_recall"]:
        failures.append("critical_defect_recall_below_threshold")
    if metrics.overall_accuracy < THRESHOLDS["overall_accuracy"]:
        failures.append("overall_accuracy_below_threshold")
    if metrics.checkpoint_accuracy < THRESHOLDS["checkpoint_accuracy"]:
        failures.append("checkpoint_accuracy_below_threshold")
    if metrics.evidence_acceptance_rate < THRESHOLDS["evidence_acceptance_rate"]:
        failures.append("evidence_acceptance_rate_below_threshold")
    if metrics.same_image_repeat_stability < THRESHOLDS["same_image_repeat_stability"]:
        failures.append("same_image_repeat_stability_below_threshold")

    passed = not failures
    if not passed:
        return ExamOutcome(passed=False, failures=failures, resulting_status=InspectorStatus.EXAM_FAILED)

    return ExamOutcome(
        passed=True,
        failures=[],
        resulting_status=InspectorStatus.EXAM_PASSED,
    )
