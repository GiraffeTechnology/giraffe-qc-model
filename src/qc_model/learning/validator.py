"""Validation of learning provider output before persistence (PRD §16).

Fail closed: unsupported categories, AI-role/category mismatches, and
AI-primary physical measurement are all rejected (or normalized to a
supervisor-review-safe state). Provider failure must never create applied
rules.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.qc_model.learning.schemas import (
    LearnedDetectionPointProposal,
    QCRuleLearningResponse,
)
from src.qc_model.schemas.checkpoint import (
    ai_can_be_primary_judge,
    default_ai_role,
    is_supported_category,
)

_PRIMARY_ROLE = "primary_visual_judge"


@dataclass
class ValidationResult:
    valid: bool
    normalized: QCRuleLearningResponse | None
    errors: list[str] = field(default_factory=list)


def _validate_proposal(p: LearnedDetectionPointProposal) -> tuple[LearnedDetectionPointProposal, list[str]]:
    errors: list[str] = []
    update: dict = {}

    # Required identity fields.
    if not p.proposed_code:
        errors.append("proposal_missing_code")

    # Category must be supported.
    if not is_supported_category(p.proposed_checkpoint_category):
        errors.append(f"unsupported_category:{p.proposed_checkpoint_category}")
        return p, errors

    category = p.proposed_checkpoint_category

    # AI role must match the category's allowed default role. If it doesn't, we
    # normalize it to the safe default (never trust an over-permissive role).
    expected_role = default_ai_role(category).value
    if p.proposed_ai_role != expected_role:
        update["proposed_ai_role"] = expected_role

    # Physical measurement (and any non-visual category) can never be AI-primary.
    if not ai_can_be_primary_judge(category) and p.proposed_ai_role == _PRIMARY_ROLE:
        update["proposed_ai_role"] = expected_role
        # Not an error — it's normalized to record_only/assistant/etc.

    # Confidence must be numeric (pydantic guarantees float); clamp to [0,1].
    if p.confidence < 0 or p.confidence > 1:
        update["confidence"] = max(0.0, min(1.0, p.confidence))

    # Uncertainties must be an explicit list (pydantic default handles None).
    if p.uncertainties is None:
        update["uncertainties"] = []

    # Every proposal must require supervisor confirmation.
    if not p.requires_supervisor_confirmation:
        update["requires_supervisor_confirmation"] = True

    if update:
        p = p.model_copy(update=update)
    return p, errors


def validate_response(response: QCRuleLearningResponse) -> ValidationResult:
    """Validate + normalize a provider response.

    Returns ``valid=False`` if the response itself is invalid or any proposal
    has an unrecoverable error (e.g. unsupported category). AI-role mismatches
    and out-of-range confidence are normalized, not rejected.
    """
    if not response.valid:
        return ValidationResult(
            valid=False,
            normalized=None,
            errors=[response.error or "provider_returned_invalid"],
        )

    all_errors: list[str] = []
    normalized_proposals: list[LearnedDetectionPointProposal] = []
    for p in response.detection_point_proposals:
        np, errs = _validate_proposal(p)
        normalized_proposals.append(np)
        all_errors.extend(errs)

    if all_errors:
        return ValidationResult(valid=False, normalized=None, errors=all_errors)

    normalized = response.model_copy(update={"detection_point_proposals": normalized_proposals})
    return ValidationResult(valid=True, normalized=normalized, errors=[])
