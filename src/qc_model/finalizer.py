"""Deterministic finalizer (PRD §14.4).

The model-level ``overall_result`` is NEVER trusted. The authoritative overall
result is re-derived here from the checkpoint-level results plus a fixed set of
safety guardrails. The single hardest invariant: **a model-level ``pass`` can
never override a checkpoint-level ``fail``**.

Precedence used to derive the overall result (highest wins):

    1. invalid / unparseable model output            → review_required
    2. capture quality unacceptable                  → review_required
    3. any *critical* checkpoint fail                → fail
    4. any checkpoint review_required (incl. forced) → review_required
    5. any checkpoint fail (non-critical)            → fail
    6. all required checkpoints pass                 → pass

Guardrails that *force a single checkpoint* to ``review_required`` before the
overall is computed:
    - checkpoint category is unconfirmed
    - checkpoint category is unsupported
    - checkpoint category is physical_measurement (AI is not the primary judge)
    - evidence is required but missing
A checkpoint the model never reported is also forced to ``review_required``.

Note on precedence: a *critical* fail outranks review_required (PRD §14.4
rule 2: review_required "unless another critical checkpoint is fail").
"""
from __future__ import annotations

from typing import Optional

from src.qc_model.providers.base import VisualInspectionResponse
from src.qc_model.schemas.checkpoint import (
    CheckpointCategory,
    ai_can_be_primary_judge,
    is_supported_category,
)
from src.qc_model.schemas.detection_point import DetectionPoint
from src.qc_model.schemas.inspection import (
    CaptureQuality,
    CheckpointResult,
    IncidentalFinding,
    InspectionResult,
)

_VALID_VERDICTS = {"pass", "fail", "review_required"}


def _force(reason: str) -> tuple[str, str]:
    return "review_required", reason


def _finalize_checkpoint(
    point: DetectionPoint,
    raw_result: Optional[str],
    evidence: str,
) -> tuple[str, str]:
    """Return (verdict, note) for one checkpoint after applying guardrails."""
    category = point.confirmed_checkpoint_category

    # Guardrail: a supervisor must have confirmed a category.
    if category is None or point.category_confirmed_by is None:
        return _force("checkpoint_category_unconfirmed")

    # Guardrail: the confirmed category must be supported.
    if not is_supported_category(category):
        return _force("checkpoint_category_unsupported")

    # Guardrail: physical measurement — AI is not the primary judge.
    if not ai_can_be_primary_judge(category):
        # rule_verification / subjective_judgment / physical_measurement: AI
        # cannot finalize a pass/fail on its own → defer to human/rule layer.
        return _force(f"ai_not_primary_judge_for_{category}")

    # The model must have actually reported this checkpoint.
    if raw_result is None:
        return _force("checkpoint_result_not_provided")

    if raw_result not in _VALID_VERDICTS:
        return _force("checkpoint_result_invalid")

    # Guardrail: evidence required but missing → cannot trust a pass/fail.
    if point.evidence_required and raw_result in ("pass", "fail") and not evidence.strip():
        return _force("evidence_required_but_missing")

    return raw_result, ""


def finalize(
    *,
    inspection_id: str,
    response: VisualInspectionResponse,
    detection_points: list[DetectionPoint],
    capture_quality: CaptureQuality,
    runtime_profile: str = "",
    training_pack_id: str = "",
    playbook_version: str = "",
) -> InspectionResult:
    """Deterministically finalize one inspection."""

    base = dict(
        inspection_id=inspection_id,
        model_provider=response.provider,
        model_name=response.model,
        runtime_profile=runtime_profile,
        training_pack_id=training_pack_id,
        playbook_version=playbook_version,
        capture_quality=capture_quality,
        confidence=response.confidence,
    )

    # No confirmed detection points → nothing AI may judge → review_required.
    if not detection_points:
        return InspectionResult(
            overall_result="review_required",
            checkpoint_results=[],
            finalization_rule_applied="no_detection_points",
            requires_human_review=True,
            **base,
        )

    # Invalid model output fails closed regardless of anything else.
    if not response.valid:
        return InspectionResult(
            overall_result="review_required",
            checkpoint_results=[
                CheckpointResult(
                    code=dp.code,
                    checkpoint_category=dp.confirmed_checkpoint_category or dp.proposed_checkpoint_category,
                    result="review_required",
                    severity=dp.severity,
                    requires_human_review=True,
                    finalization_note="invalid_model_output",
                )
                for dp in detection_points
            ],
            finalization_rule_applied="invalid_model_output",
            requires_human_review=True,
            **base,
        )

    # Index raw provider checkpoint results by code.
    raw_by_code = {cp.code: cp for cp in response.checkpoint_results}

    checkpoint_results: list[CheckpointResult] = []
    for dp in detection_points:
        raw = raw_by_code.get(dp.code)
        raw_result = raw.result if raw is not None else None
        evidence = raw.visual_evidence if raw is not None else ""
        verdict, note = _finalize_checkpoint(dp, raw_result, evidence)
        checkpoint_results.append(
            CheckpointResult(
                code=dp.code,
                checkpoint_category=dp.confirmed_checkpoint_category or dp.proposed_checkpoint_category,
                result=verdict,
                visual_evidence=evidence,
                normal_vs_defect_reasoning=getattr(raw, "normal_vs_defect_reasoning", "") if raw else "",
                pseudo_defect_analysis=getattr(raw, "pseudo_defect_analysis", "") if raw else "",
                confidence=getattr(raw, "confidence", 0.0) if raw else 0.0,
                severity=dp.severity,
                requires_human_review=(verdict == "review_required"),
                finalization_note=note,
            )
        )

    incidental = [
        IncidentalFinding(
            description=f.description,
            severity=f.severity if f.severity in ("minor", "major", "critical") else "minor",
            visual_evidence=f.visual_evidence,
            requires_human_review=f.requires_human_review or f.severity == "critical",
        )
        for f in response.incidental_findings
    ]

    overall, rule = _derive_overall(checkpoint_results, capture_quality, incidental)

    requires_review = overall == "review_required" or any(
        cp.requires_human_review for cp in checkpoint_results
    )

    return InspectionResult(
        overall_result=overall,
        checkpoint_results=checkpoint_results,
        incidental_findings=incidental,
        finalization_rule_applied=rule,
        requires_human_review=requires_review,
        **base,
    )


def _derive_overall(
    checkpoint_results: list[CheckpointResult],
    capture_quality: CaptureQuality,
    incidental: list[IncidentalFinding],
) -> tuple[str, str]:
    """Re-derive the authoritative overall verdict. Never trusts model overall."""
    verdicts = [(cp.result, cp.severity) for cp in checkpoint_results]

    critical_fail = any(v == "fail" and sev == "critical" for v, sev in verdicts)
    if critical_fail:
        # Critical fail outranks even capture problems and review_required.
        return "fail", "critical_checkpoint_fail"

    if not capture_quality.acceptable:
        return "review_required", "capture_quality_unacceptable"

    if any(v == "review_required" for v, _ in verdicts):
        return "review_required", "checkpoint_review_required"

    # Incidental critical abnormality defers to human (PRD §17).
    if any(f.severity == "critical" for f in incidental):
        return "review_required", "incidental_critical_finding"

    if any(v == "fail" for v, _ in verdicts):
        return "fail", "checkpoint_fail"

    return "pass", "all_checkpoints_pass"
