"""Deterministic / mocked source extractor (PR 21 §5).

IMPORTANT: This is a PLACEHOLDER for the real LLM/VLM extraction that lands in
PR 22/23. It uses simple deterministic heuristics (regex for numeric tolerance
patterns, keyword matching for "must" / "shall" / "count" / "align" / "±", …)
purely to exercise the full pipeline shape. It is NOT accurate extraction and
produces DRAFT fragments only — nothing here can become an active rule.

The output fragment shapes are stable so PR 22 can swap in a real extractor
without a schema change.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.qc_model.ingestion.types import (
    CandidateLabel,
    FragmentType,
    QCSourceType,
    TEXTUAL_SOURCE_TYPES,
)

PROVIDER_NAME = "deterministic_mock_extractor_v1"

# ── Heuristic vocabularies (placeholder signals only) ─────────────────────
_NUMERIC_TOLERANCE = re.compile(
    r"(±|\+/-|\+\s*/\s*-|\btolerance\b|\bwithin\b\s*\d|"
    r"\d+(\.\d+)?\s*(mm|cm|m|g|kg|°|deg|degrees?|%|pcs))",
    re.IGNORECASE,
)
_MEASUREMENT_KEYWORDS = re.compile(
    r"\b(length|width|height|thickness|diameter|weight|spacing|angle|count|"
    r"gap|pitch|hardness|tensile|dimension)\b",
    re.IGNORECASE,
)
_DETECTION_KEYWORDS = re.compile(
    r"\b(must|shall|should|align|aligned|centered|centred|symmetr|missing|"
    r"crack|scratch|stain|chip|deform|defect|color|colour|surface|assembl)\w*",
    re.IGNORECASE,
)
_BOUNDARY_KEYWORDS = re.compile(
    r"\b(acceptable if|reject if|allowed|not allowed|boundary|threshold|"
    r"within tolerance|out of tolerance|pass if|fail if)\b",
    re.IGNORECASE,
)
_PSEUDO_DEFECT_KEYWORDS = re.compile(
    r"\b(reflection|glare|shadow|blur|overexpos|underexpos|highlight|"
    r"angle-induced|pseudo|artifact|artefact)\w*",
    re.IGNORECASE,
)
_REVIEW_KEYWORDS = re.compile(
    r"(\btbd\b|\bto be decided\b|\bunclear\b|\bsupervisor\b|\breview\b|\?\s*$)",
    re.IGNORECASE,
)


@dataclass
class ExtractedFragment:
    fragment_type: str
    candidate_label: str
    text: str
    rationale: str = ""
    source_excerpt: str = ""
    confidence: float = 0.5
    # Optional drafts derived from this fragment.
    requirement_draft: str | None = None
    requirement_category: str | None = None
    boundary_draft: str | None = None
    boundary_kind: str | None = None


@dataclass
class ExtractionOutput:
    provider: str = PROVIDER_NAME
    fragments: list[ExtractedFragment] = field(default_factory=list)


def _split_statements(text: str) -> list[str]:
    parts = re.split(r"[\n\r]+|(?<=[.;])\s+", text or "")
    out: list[str] = []
    for part in parts:
        p = re.sub(r"^\s*(\d+[.)]|[-*])\s*", "", part).strip()
        if p:
            out.append(p)
    return out


def _classify_statement(statement: str) -> ExtractedFragment:
    excerpt = statement[:280]

    has_measure_kw = bool(_MEASUREMENT_KEYWORDS.search(statement))
    has_number = bool(_NUMERIC_TOLERANCE.search(statement))

    # 1. Measurement keyword + a number/tolerance → physical measurement.
    if has_measure_kw and has_number:
        return ExtractedFragment(
            fragment_type=FragmentType.POSSIBLE_PHYSICAL_MEASUREMENT.value,
            candidate_label=CandidateLabel.BOUNDARY_RULE.value,
            text=statement,
            rationale="Measurement keyword with a numeric tolerance/quantity.",
            source_excerpt=excerpt,
            confidence=0.6,
            boundary_draft=statement,
            boundary_kind="physical_measurement",
        )

    # 2. Measurement keyword but NO number → missing tolerance/count.
    if has_measure_kw and not has_number:
        return ExtractedFragment(
            fragment_type=FragmentType.MISSING_TOLERANCE_OR_COUNT.value,
            candidate_label=CandidateLabel.BOUNDARY_RULE.value,
            text=statement,
            rationale="Measurement/count requirement without an explicit tolerance or number.",
            source_excerpt=excerpt,
            confidence=0.55,
            boundary_draft=statement,
            boundary_kind="physical_measurement",
        )

    # 3. Explicit boundary/threshold phrasing → boundary condition.
    if _BOUNDARY_KEYWORDS.search(statement):
        return ExtractedFragment(
            fragment_type=FragmentType.POSSIBLE_BOUNDARY_CONDITION.value,
            candidate_label=CandidateLabel.BOUNDARY_RULE.value,
            text=statement,
            rationale="Contains acceptance/rejection boundary phrasing.",
            source_excerpt=excerpt,
            confidence=0.55,
            boundary_draft=statement,
            boundary_kind="rule_verification",
        )

    # 4. Pseudo-defect vocabulary → possible pseudo defect.
    if _PSEUDO_DEFECT_KEYWORDS.search(statement):
        return ExtractedFragment(
            fragment_type=FragmentType.POSSIBLE_PSEUDO_DEFECT.value,
            candidate_label=CandidateLabel.BOUNDARY_RULE.value,
            text=statement,
            rationale="Mentions a capture artifact / pseudo-defect signal.",
            source_excerpt=excerpt,
            confidence=0.5,
        )

    # 5. Explicit review/uncertainty markers → requires supervisor review.
    if _REVIEW_KEYWORDS.search(statement):
        return ExtractedFragment(
            fragment_type=FragmentType.REQUIRES_SUPERVISOR_REVIEW.value,
            candidate_label=CandidateLabel.REVIEW.value,
            text=statement,
            rationale="Explicitly flagged for review or marked undecided.",
            source_excerpt=excerpt,
            confidence=0.4,
        )

    # 6. Requirement / defect vocabulary → possible detection point.
    if _DETECTION_KEYWORDS.search(statement):
        return ExtractedFragment(
            fragment_type=FragmentType.POSSIBLE_DETECTION_POINT.value,
            candidate_label=CandidateLabel.DETECTION_POINT.value,
            text=statement,
            rationale="Contains a checkable visual requirement (must/shall/align/defect terms).",
            source_excerpt=excerpt,
            confidence=0.6,
            requirement_draft=statement,
            requirement_category="visual_defect",
        )

    # 7. No recognizable signal → unclear requirement.
    return ExtractedFragment(
        fragment_type=FragmentType.UNCLEAR_REQUIREMENT.value,
        candidate_label=CandidateLabel.REVIEW.value,
        text=statement,
        rationale="No recognizable QC signal in this statement.",
        source_excerpt=excerpt,
        confidence=0.3,
    )


def extract(source_type: str, text_content: str | None, file_ref: str | None) -> ExtractionOutput:
    """Run deterministic extraction over a source document.

    Textual sources are parsed statement-by-statement. Binary/image sources
    (drawings, images, samples, CAD, PDF) have no parseable text in this PR, so
    they yield a single ``requires_supervisor_review`` fragment noting that a
    real VLM pass (PR 22/23) is needed.
    """
    output = ExtractionOutput()

    try:
        stype = QCSourceType(source_type)
    except ValueError:
        # Should never happen (API validates), but fail safe to review.
        output.fragments.append(
            ExtractedFragment(
                fragment_type=FragmentType.REQUIRES_SUPERVISOR_REVIEW.value,
                candidate_label=CandidateLabel.REVIEW.value,
                text=f"Unrecognized source type: {source_type}",
                rationale="Unknown source type reached the extractor.",
            )
        )
        return output

    if stype in TEXTUAL_SOURCE_TYPES and text_content and text_content.strip():
        for statement in _split_statements(text_content):
            output.fragments.append(_classify_statement(statement))
        if not output.fragments:
            output.fragments.append(
                ExtractedFragment(
                    fragment_type=FragmentType.UNCLEAR_REQUIREMENT.value,
                    candidate_label=CandidateLabel.REVIEW.value,
                    text=text_content.strip()[:280],
                    rationale="No parseable statements found.",
                )
            )
        return output

    # Binary / image / file reference source.
    ref = file_ref or "(no file reference)"
    output.fragments.append(
        ExtractedFragment(
            fragment_type=FragmentType.REQUIRES_SUPERVISOR_REVIEW.value,
            candidate_label=CandidateLabel.REVIEW.value,
            text=(
                f"{stype.value} reference registered ({ref}). Visual/CAD content "
                "requires real VLM extraction (PR 22/23)."
            ),
            rationale="Binary/image source has no parseable text in PR 21.",
            source_excerpt=ref[:280],
            confidence=0.2,
        )
    )
    return output
