"""Enums for the QC Source Ingestion Workbench (PR 21 §3, §5)."""
from __future__ import annotations

from enum import Enum


class QCSourceType(str, Enum):
    """Recognized source material types (PR 21 §3)."""

    NATURAL_LANGUAGE = "natural_language"
    PROCESS_SPEC = "process_spec"
    # Process card (工艺卡) — a manufacturing/QC routing card supplied as a
    # standard-authoring input (PRD Authoring Extension §1). It is a *source
    # format*, not a payload shape: the concrete document (image / PDF / Word /
    # Excel / CAD) is classified and routed by
    # :mod:`src.qc_model.ingestion.process_card`.
    PROCESS_CARD = "process_card"
    INSPECTION_STANDARD = "inspection_standard"
    DRAWING = "drawing"
    CAD_EXPORT = "cad_export"
    PDF = "pdf"
    IMAGE = "image"
    STANDARD_PHOTO = "standard_photo"
    POSITIVE_SAMPLE = "positive_sample"
    DEFECT_SAMPLE = "defect_sample"
    BOUNDARY_SAMPLE = "boundary_sample"
    CAPTURE_ARTIFACT_SAMPLE = "capture_artifact_sample"
    SPEECH_TO_TEXT = "speech_to_text"


# Source types whose payload is textual and can be parsed by the deterministic
# extractor. Everything else is a binary/image reference that a real VLM would
# read in a later PR.
TEXTUAL_SOURCE_TYPES = {
    QCSourceType.NATURAL_LANGUAGE,
    QCSourceType.PROCESS_SPEC,
    QCSourceType.INSPECTION_STANDARD,
    QCSourceType.SPEECH_TO_TEXT,
}


class FragmentType(str, Enum):
    """Classification of an extracted candidate fragment (PR 21 §5)."""

    POSSIBLE_DETECTION_POINT = "possible_detection_point"
    POSSIBLE_PHYSICAL_MEASUREMENT = "possible_physical_measurement"
    POSSIBLE_BOUNDARY_CONDITION = "possible_boundary_condition"
    MISSING_TOLERANCE_OR_COUNT = "missing_tolerance_or_count"
    POSSIBLE_PSEUDO_DEFECT = "possible_pseudo_defect"
    UNCLEAR_REQUIREMENT = "unclear_requirement"
    REQUIRES_SUPERVISOR_REVIEW = "requires_supervisor_review"


class CandidateLabel(str, Enum):
    """UI grouping hint for a fragment (badge only — no action in PR 21)."""

    DETECTION_POINT = "detection_point"
    BOUNDARY_RULE = "boundary_rule"
    REVIEW = "review"


def is_valid_source_type(value: str) -> bool:
    return value in {t.value for t in QCSourceType}
