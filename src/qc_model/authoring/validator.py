"""Hard validator for authored proposals (PR 22 §4, §5, §8).

Two invariants enforced in code (independent of the LLM):

1. Physical-measurement guard: if ``checkpoint_category == physical_measurement``
   then ``ai_role`` is forced to ``record_only`` — whatever the LLM returned —
   and the override is recorded in a supervisor-visible note.
2. Fail-closed structure: a malformed proposal (not a dict, or missing required
   keys) fails the whole job. Never best-effort-parse partial output into an
   approvable proposal.

The four checkpoint categories are the single source of truth from
``src.qc_model.schemas.checkpoint`` (reused, not duplicated).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.qc_model.schemas.checkpoint import CheckpointCategory, is_supported_category

PHYSICAL_MEASUREMENT = CheckpointCategory.PHYSICAL_MEASUREMENT.value
RECORD_ONLY = "record_only"

# Keys a raw proposal must contain (values may be empty, but keys must exist).
_REQUIRED_KEYS = {
    "source_fragment_id",
    "proposed_code",
    "checkpoint_category",
    "ai_role",
}


@dataclass
class ValidatedProposal:
    source_fragment_id: str
    proposed_code: str
    proposed_name: str
    checkpoint_category: str
    ai_role: str
    decision_rule: str = ""
    review_required_conditions: list = field(default_factory=list)
    normal_visual_features: list = field(default_factory=list)
    defect_visual_features: list = field(default_factory=list)
    known_pseudo_defects: list = field(default_factory=list)
    questions_or_ambiguities: list = field(default_factory=list)
    evidence_required: list = field(default_factory=list)
    severity: str = "major"
    confidence: float = 0.0
    guard_override_note: str = ""


@dataclass
class ValidationResult:
    valid: bool
    proposals: list[ValidatedProposal] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _as_list(value) -> list:
    return list(value) if isinstance(value, (list, tuple)) else []


def _validate_one(raw: object) -> tuple[ValidatedProposal | None, str | None]:
    if not isinstance(raw, dict):
        return None, "proposal_is_not_an_object"
    missing = _REQUIRED_KEYS - set(raw.keys())
    if missing:
        return None, f"missing_required_keys:{sorted(missing)}"

    category = str(raw.get("checkpoint_category") or "")
    ai_role = str(raw.get("ai_role") or "")
    questions = _as_list(raw.get("questions_or_ambiguities"))
    override_note = ""

    # Unsupported non-empty category → blank it (unresolved) and flag for review
    # rather than trust a garbage category.
    if category and not is_supported_category(category):
        questions = questions + [f"unsupported checkpoint_category from model: {category!r}"]
        category = ""

    # HARD physical-measurement guard: force record_only regardless of the LLM.
    if category == PHYSICAL_MEASUREMENT and ai_role != RECORD_ONLY:
        override_note = (
            f"physical-measurement guard: ai_role {ai_role or '(empty)'!r} overridden to "
            f"'record_only' (AI cannot be primary judge for physical measurement)."
        )
        ai_role = RECORD_ONLY

    proposal = ValidatedProposal(
        source_fragment_id=str(raw["source_fragment_id"]),
        proposed_code=str(raw["proposed_code"]),
        proposed_name=str(raw.get("proposed_name") or raw["proposed_code"]),
        checkpoint_category=category,
        ai_role=ai_role,
        decision_rule=str(raw.get("decision_rule") or ""),
        review_required_conditions=_as_list(raw.get("review_required_conditions")),
        normal_visual_features=_as_list(raw.get("normal_visual_features")),
        defect_visual_features=_as_list(raw.get("defect_visual_features")),
        known_pseudo_defects=_as_list(raw.get("known_pseudo_defects")),
        questions_or_ambiguities=questions,
        evidence_required=_as_list(raw.get("evidence_required")),
        severity=str(raw.get("severity") or "major"),
        confidence=float(raw.get("confidence") or 0.0),
        guard_override_note=override_note,
    )
    return proposal, None


def validate_response(response) -> ValidationResult:
    """Validate + guard a provider response.

    Fails closed (``valid=False``) if the provider failed or ANY proposal is
    malformed — no partial persistence.
    """
    if not getattr(response, "valid", False):
        return ValidationResult(valid=False, errors=[getattr(response, "error", None) or "provider_invalid"])

    validated: list[ValidatedProposal] = []
    errors: list[str] = []
    for raw in response.proposals:
        proposal, err = _validate_one(raw)
        if err:
            errors.append(err)
        else:
            validated.append(proposal)

    if errors:
        # Any malformed proposal fails the whole job closed.
        return ValidationResult(valid=False, errors=errors)

    return ValidationResult(valid=True, proposals=validated)
