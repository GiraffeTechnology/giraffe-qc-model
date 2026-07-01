"""Capture quality gate (PRD §16).

If capture quality prevents reliable inspection, the result is
``review_required`` — never a pass.
"""
from __future__ import annotations

from src.qc_model.providers.base import ProviderCaptureQuality
from src.qc_model.schemas.inspection import CaptureQuality

# Issue codes that, if present, make capture unacceptable (PRD §16).
KNOWN_CAPTURE_ISSUES = {
    "blur",
    "overexposure",
    "underexposure",
    "wrong_angle",
    "target_region_not_visible",
    "occlusion",
    "strong_shadow",
    "wrong_background",
    "low_resolution",
}


def evaluate_capture_quality(provider_quality: ProviderCaptureQuality) -> CaptureQuality:
    """Normalize a provider's capture-quality claim into the result schema.

    Capture is acceptable only if the provider says so *and* it reported no
    known blocking issues (fail closed if issues are present).
    """
    issues = list(provider_quality.issues or [])
    acceptable = bool(provider_quality.acceptable) and not issues
    return CaptureQuality(acceptable=acceptable, issues=issues)
