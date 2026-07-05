"""Physical-measurement boundary helpers (PRD §5).

If a checkpoint is better measured by a ruler/gauge/fixture/caliper/scale, AI
must not be the primary judge. AI may only record evidence, guide the
operator, capture proof, archive results, and flag missing measurement
evidence.

The chain-link-count case is kept ONLY as a boundary example of what AI should
not primarily judge when a physical fixture/ruler is more appropriate.
"""
from __future__ import annotations

from src.qc_model.schemas.checkpoint import (
    CheckpointCategory,
    ai_can_be_primary_judge,
)

# Deterministic hints: keywords that strongly suggest a physical measurement.
_PHYSICAL_MEASUREMENT_HINTS = {
    "length",
    "width",
    "height",
    "thickness",
    "weight",
    "diameter",
    "hole diameter",
    "hole size",
    "spacing",
    "chain link count",
    "chain-link count",
    "link count",
    "angle",
    "capacity",
    "hardness",
    "tensile",
    "tension",
    "chemical composition",
    "laboratory test",
}

# What AI may do for a physical-measurement checkpoint.
PHYSICAL_MEASUREMENT_AI_ACTIONS = (
    "record_only",
    "operator_guidance",
    "evidence_capture",
    "measurement_result_archiving",
)


def suggest_category(requirement_text: str) -> str:
    """Deterministic category *suggestion* from raw requirement text.

    This only proposes a category — a QC supervisor must still confirm it.
    Anything matching a physical-measurement hint is proposed as
    ``physical_measurement`` so AI is never silently made the primary judge.
    """
    text = (requirement_text or "").lower()
    for hint in _PHYSICAL_MEASUREMENT_HINTS:
        if hint in text:
            return CheckpointCategory.PHYSICAL_MEASUREMENT.value
    return CheckpointCategory.VISUAL_DEFECT.value


def assert_ai_not_primary(category: str) -> None:
    """Raise if someone tries to make AI primary for a non-visual category."""
    if ai_can_be_primary_judge(category):
        return
    raise PhysicalMeasurementBoundaryError(
        f"AI cannot be the primary judge for checkpoint_category={category!r}; "
        f"allowed AI actions are {PHYSICAL_MEASUREMENT_AI_ACTIONS}."
    )


class PhysicalMeasurementBoundaryError(ValueError):
    """Raised when AI-primary judgment is requested for a non-visual category."""
