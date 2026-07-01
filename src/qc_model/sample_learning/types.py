"""Enums for the VLM sample-learning pipeline (PR 23 §2, §3)."""
from __future__ import annotations

from enum import Enum


class SampleType(str, Enum):
    REFERENCE = "reference"
    POSITIVE = "positive"
    DEFECT = "defect"
    BOUNDARY = "boundary"
    CAPTURE_ARTIFACT = "capture_artifact"


class FeatureType(str, Enum):
    NORMAL_FEATURE = "normal_feature"
    ACCEPTABLE_VARIATION = "acceptable_variation"
    DEFECT_FEATURE = "defect_feature"
    PSEUDO_DEFECT = "pseudo_defect"
    CAPTURE_ARTIFACT_RISK = "capture_artifact_risk"


# Status values shared by memory / rules (draft-lifecycle; no "active").
STATUS_PROPOSED = "proposed"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_APPLIED = "applied"


def is_valid_sample_type(value: str) -> bool:
    return value in {t.value for t in SampleType}


# Which feature_type a given sample_type primarily produces.
SAMPLE_TYPE_TO_FEATURE: dict[SampleType, FeatureType] = {
    SampleType.REFERENCE: FeatureType.NORMAL_FEATURE,
    SampleType.POSITIVE: FeatureType.ACCEPTABLE_VARIATION,
    SampleType.DEFECT: FeatureType.DEFECT_FEATURE,
    SampleType.BOUNDARY: FeatureType.ACCEPTABLE_VARIATION,
    SampleType.CAPTURE_ARTIFACT: FeatureType.CAPTURE_ARTIFACT_RISK,
}
