"""Deterministic fragment → rule-proposal classifier (PR 22 §3, §5).

This is a PLACEHOLDER for a real LLM. It implements the four worked examples
(A–D) and the missing-information rules with simple, deterministic heuristics so
the authoring pipeline is fully testable without a live model. It NEVER
fabricates a missing value (count, tolerance, view, orientation, color range,
measurement method, threshold) — it raises a ``questions_or_ambiguities`` entry
instead.

The physical-measurement guard is NOT applied here; it is enforced separately in
``validator`` so it holds even against a hostile/real LLM.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_MEASUREMENT_KEYWORDS = re.compile(
    r"\b(diameter|length|width|height|thickness|weight|gap|spacing|pitch|"
    r"dimension|size|radius|depth|clearance)\b",
    re.IGNORECASE,
)
_COUNT_KEYWORD = re.compile(r"\bcount\b", re.IGNORECASE)
_ALIGN_KEYWORDS = re.compile(
    r"\b(align|aligned|alignment|axis|centered|centred|centre|center|symmetr\w*|concentric)\b",
    re.IGNORECASE,
)
_VISUAL_KEYWORDS = re.compile(
    r"\b(visible|glue overflow|overflow|scratch|crack|chip|stain|deform\w*|"
    r"defect|surface|missing|discolor\w*|color|colour|blemish|dent)\b",
    re.IGNORECASE,
)
_NUMERIC_TOLERANCE = re.compile(
    r"(±|\+/-|\+\s*/\s*-|\d+(\.\d+)?\s*(mm|cm|m|g|kg|°|deg|degrees?|%|pcs|pieces?))",
    re.IGNORECASE,
)
_INTEGER = re.compile(r"\b\d+\b")
_VIEW_PHRASE = re.compile(
    r"\b(front|top|bottom|back|rear|side|left|right|oblique)\s+view\b|"
    r"\bfrom (the )?(front|top|bottom|back|side)\b",
    re.IGNORECASE,
)

_STOPWORDS = {"the", "a", "an", "is", "are", "must", "shall", "should", "of", "with", "from",
              "no", "any", "be", "to", "and", "or"}


@dataclass
class AuthoredProposal:
    proposed_code: str
    proposed_name: str
    checkpoint_category: str  # "" means unresolved (supervisor must classify)
    ai_role: str  # "" means unresolved
    decision_rule: str = ""
    review_required_conditions: list[str] = field(default_factory=list)
    normal_visual_features: list[str] = field(default_factory=list)
    defect_visual_features: list[str] = field(default_factory=list)
    known_pseudo_defects: list[str] = field(default_factory=list)
    questions_or_ambiguities: list[str] = field(default_factory=list)
    evidence_required: list[str] = field(default_factory=list)
    severity: str = "major"
    confidence: float = 0.5


def _slug(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS]
    return "_".join(words[:5]) or "detection_point"


def _name(text: str) -> str:
    t = text.strip().rstrip(".;")
    return (t[:1].upper() + t[1:])[:120] if t else "Detection point"


def classify_fragment(text: str) -> AuthoredProposal:
    """Classify one fragment's text into a structured rule proposal."""
    fragment = (text or "").strip()
    code, name = _slug(fragment), _name(fragment)
    has_number = bool(_NUMERIC_TOLERANCE.search(fragment))
    has_view = bool(_VIEW_PHRASE.search(fragment))

    # 1. Physical measurement (Example A). Measurement keyword dominates.
    if _MEASUREMENT_KEYWORDS.search(fragment):
        questions: list[str] = []
        if not has_number:
            questions.append("exact dimension / tolerance is not specified in the source")
        return AuthoredProposal(
            proposed_code=code,
            proposed_name=name,
            checkpoint_category="physical_measurement",
            ai_role="record_only",
            decision_rule=(
                "Operator must measure this dimension with a calibrated gauge / caliper; "
                "AI records the measurement evidence only and does not judge pass/fail."
            ),
            review_required_conditions=["measurement evidence missing", "gauge/caliper photo missing"],
            questions_or_ambiguities=questions,
            evidence_required=["operator-recorded measurement value", "calibrated tool / fixture photo"],
            confidence=0.6,
        )

    # 2. Rule verification via count (Example C).
    if _COUNT_KEYWORD.search(fragment):
        questions = ["required view angle for counting is not specified in the source"]
        if not _INTEGER.search(fragment):
            questions.insert(0, "exact count value is not specified in the source")
        return AuthoredProposal(
            proposed_code=code,
            proposed_name=name,
            checkpoint_category="rule_verification",
            ai_role="information_extraction",
            decision_rule=(
                "Verify the counted quantity matches the specified value via information "
                "extraction; final judgment is deterministic rule-based."
            ),
            review_required_conditions=["counting view angle unclear", "occluded items"],
            questions_or_ambiguities=questions,
            evidence_required=["image where all items are countable"],
            confidence=0.55,
        )

    # 3. Alignment / axis (Example B). Category is visual, but AI role stays
    #    unresolved unless a clear reference/view is available.
    if _ALIGN_KEYWORDS.search(fragment):
        sufficient_evidence = has_view
        ai_role = "primary_visual_judge" if sufficient_evidence else ""
        questions = []
        if not sufficient_evidence:
            questions.append(
                "reference axis / alignment datum is unclear; insufficient visual evidence "
                "to make AI the primary judge"
            )
        return AuthoredProposal(
            proposed_code=code,
            proposed_name=name,
            checkpoint_category="visual_defect",
            ai_role=ai_role,
            decision_rule=(
                "Fail if the subject is misaligned relative to the reference axis and the "
                "deviation cannot be explained by a capture artifact."
            ),
            review_required_conditions=["oblique viewing angle", "unclear reference axis"],
            defect_visual_features=["visible offset from the reference axis"],
            questions_or_ambiguities=questions,
            evidence_required=["reference image defining the alignment axis"],
            confidence=0.5,
        )

    # 4. Visual defect (Example D).
    if _VISUAL_KEYWORDS.search(fragment):
        sufficient_evidence = has_view
        ai_role = "primary_visual_judge" if sufficient_evidence else ""
        questions = []
        if not sufficient_evidence:
            questions.append("required view is not specified in the source")
        return AuthoredProposal(
            proposed_code=code,
            proposed_name=name,
            checkpoint_category="visual_defect",
            ai_role=ai_role,
            decision_rule=(
                "Fail if the described visual defect is present and cannot be explained by a "
                "capture artifact."
            ),
            review_required_conditions=["shadow", "reflection", "blur"],
            defect_visual_features=[name],
            known_pseudo_defects=["reflection", "shadow", "blur", "overexposure"],
            questions_or_ambiguities=questions,
            evidence_required=["reference image showing acceptable condition"],
            confidence=0.6,
        )

    # 5. Fallback — unresolved. No category guess; supervisor must classify.
    return AuthoredProposal(
        proposed_code=code,
        proposed_name=name,
        checkpoint_category="",
        ai_role="",
        decision_rule="",
        questions_or_ambiguities=[
            "requirement is unclear; supervisor must classify the checkpoint category"
        ],
        confidence=0.3,
    )
