"""Checkpoint categories and the physical-measurement boundary.

Every detection point has a ``checkpoint_category``. The category decides
whether AI may be the *primary* judge. This is the single source of truth for
the physical-measurement boundary enforced across the engine (PRD §5, §8).
"""
from __future__ import annotations

from enum import Enum


class CheckpointCategory(str, Enum):
    """Supported checkpoint categories (PRD §8)."""

    VISUAL_DEFECT = "visual_defect"
    PHYSICAL_MEASUREMENT = "physical_measurement"
    RULE_VERIFICATION = "rule_verification"
    SUBJECTIVE_JUDGMENT = "subjective_judgment"


class AIRole(str, Enum):
    """The role AI is allowed to play for a checkpoint category."""

    # visual_defect: AI may be the primary visual judge (after confirmation).
    PRIMARY_VISUAL_JUDGE = "primary_visual_judge"
    # physical_measurement: AI never judges; it records evidence only.
    RECORD_ONLY = "record_only"
    # rule_verification: deterministic rule/OCR is primary; AI extracts info.
    INFORMATION_EXTRACTION = "information_extraction"
    # subjective_judgment: AI assists; a human makes the final call.
    ASSISTANT_ONLY = "assistant_only"


_SUPPORTED = {c.value for c in CheckpointCategory}

# Only visual_defect lets AI be the *primary* judge.
_AI_PRIMARY_CATEGORIES = {CheckpointCategory.VISUAL_DEFECT}

_DEFAULT_ROLE: dict[CheckpointCategory, AIRole] = {
    CheckpointCategory.VISUAL_DEFECT: AIRole.PRIMARY_VISUAL_JUDGE,
    CheckpointCategory.PHYSICAL_MEASUREMENT: AIRole.RECORD_ONLY,
    CheckpointCategory.RULE_VERIFICATION: AIRole.INFORMATION_EXTRACTION,
    CheckpointCategory.SUBJECTIVE_JUDGMENT: AIRole.ASSISTANT_ONLY,
}


def is_supported_category(category: str | None) -> bool:
    """True if ``category`` is one of the supported checkpoint categories."""
    return category in _SUPPORTED


def ai_can_be_primary_judge(category: str | None) -> bool:
    """True only for ``visual_defect``.

    For physical_measurement, rule_verification, and subjective_judgment AI
    must not be the primary judge — and an unsupported / missing category is
    never AI-primary either (fail closed).
    """
    if not is_supported_category(category):
        return False
    return CheckpointCategory(category) in _AI_PRIMARY_CATEGORIES


def default_ai_role(category: str | None) -> AIRole:
    """Default AI role for a category; record_only for unsupported input."""
    if not is_supported_category(category):
        return AIRole.RECORD_ONLY
    return _DEFAULT_ROLE[CheckpointCategory(category)]
