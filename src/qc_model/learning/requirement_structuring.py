"""Deterministic operator-requirement structuring (no LLM).

Turns free-text operator QC requirements into structured detection-point
*proposals*. This is deterministic on purpose: the Phase 2A mock learning
provider uses it so tests validate workflow correctness without any real model.

The physical-measurement boundary is applied here via
:func:`src.qc_model.boundary.suggest_category`, so a requirement like
"verify chain link count" is proposed as ``physical_measurement`` /
``record_only`` and never AI-primary.
"""
from __future__ import annotations

import re

from src.qc_model.boundary import (
    PHYSICAL_MEASUREMENT_AI_ACTIONS,  # noqa: F401 (referenced in docs/tests)
    suggest_category,
)
from src.qc_model.schemas.checkpoint import CheckpointCategory, default_ai_role

_LEADING_VERBS = re.compile(
    r"^\s*(?:please\s+)?(?:check|verify|ensure|inspect|confirm|make sure|look at|examine)"
    r"\s+(?:whether|that|if|the|for|any)?\s*",
    re.IGNORECASE,
)

_STOPWORDS = {"the", "a", "an", "is", "are", "of", "and", "or", "to", "for", "with", "has", "have"}

# Known canonical concepts → stable codes/names. Keeps proposed codes readable
# and stable for common accessory-QC phrasings (seed SKU validation only).
_CANONICAL: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"flower.*center.*(align|center)|center.*flower", re.I),
     "flower_center_alignment", "Flower center alignment"),
    (re.compile(r"chain.*link.*count|link.*count", re.I),
     "chain_link_count", "Chain link count"),
    (re.compile(r"petal.*crack|crack.*petal", re.I),
     "petal_crack", "Petal crack"),
    (re.compile(r"pearl.*rhinestone.*count|rhinestone.*pearl.*count", re.I),
     "pearl_rhinestone_count", "Pearl and rhinestone count"),
    (re.compile(r"missing.*rhinestone|rhinestone.*missing", re.I),
     "missing_rhinestone", "Missing rhinestone"),
]


def split_requirements(text: str) -> list[str]:
    """Split a requirement blob into individual requirement statements."""
    if not text:
        return []
    # Split on newlines and sentence terminators; drop numbering like "1." / "2)".
    parts = re.split(r"[\n\r]+|(?<=[.;])\s+", text)
    cleaned: list[str] = []
    for part in parts:
        p = re.sub(r"^\s*\d+[.)]\s*", "", part).strip().rstrip(".;")
        if p:
            cleaned.append(p)
    return cleaned


def _slug(text: str) -> str:
    words = [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOPWORDS]
    return "_".join(words[:5]) or "detection_point"


def canonicalize(requirement: str) -> tuple[str, str]:
    """Return (code, name) for a single requirement statement."""
    for pattern, code, name in _CANONICAL:
        if pattern.search(requirement):
            return code, name
    core = _LEADING_VERBS.sub("", requirement).strip()
    code = _slug(core)
    name = core[:1].upper() + core[1:] if core else code
    return code, name


def structure_requirement(requirement: str) -> dict:
    """Structure one requirement statement into a detection-point proposal dict."""
    code, name = canonicalize(requirement)
    category = suggest_category(requirement)
    ai_role = default_ai_role(category).value

    if category == CheckpointCategory.PHYSICAL_MEASUREMENT.value:
        # Physical-measurement boundary (PRD §8): never AI-primary.
        return {
            "proposed_code": code,
            "proposed_name": name,
            "proposed_checkpoint_category": category,
            "proposed_ai_role": ai_role,  # record_only
            "target_region": "",
            "severity": "major",
            "normal_visual_features": [],
            "defect_visual_features": [],
            "known_pseudo_defects": [],
            "decision_rule": "measurement must be performed by operator using fixture / ruler / gauge",
            "review_required_conditions": ["measurement evidence missing", "fixture photo missing"],
            "evidence_required": True,
            "confidence": 0.7,
            "uncertainties": [],
            "source_requirement": requirement,
        }

    # Visual defect (or other visual-ish category): AI may be primary judge only
    # after supervisor confirmation. Provide generic structured features.
    severity = "critical" if re.search(r"crack|missing|broken", requirement, re.I) else "major"
    return {
        "proposed_code": code,
        "proposed_name": name,
        "proposed_checkpoint_category": category,
        "proposed_ai_role": ai_role,
        "target_region": name.lower().replace(" ", "_"),
        "severity": severity,
        "normal_visual_features": [
            f"{name} appears consistent with the reference sample.",
        ],
        "defect_visual_features": [
            f"{name} shows a visible deviation from the reference sample.",
        ],
        "known_pseudo_defects": ["reflection", "shadow", "blur", "overexposure", "angle-induced pseudo-defect"],
        "decision_rule": f"fail if {name.lower()} deviates from the confirmed standard and is not a capture artifact",
        "review_required_conditions": ["capture angle hides the target region", "image is overexposed"],
        "evidence_required": True,
        "confidence": 0.7,
        "uncertainties": [],
        "source_requirement": requirement,
    }


def structure_requirements(requirements: list[str]) -> list[dict]:
    """Structure a list of requirement statements (each may contain many)."""
    out: list[dict] = []
    for blob in requirements:
        for statement in split_requirements(blob):
            out.append(structure_requirement(statement))
    return out
