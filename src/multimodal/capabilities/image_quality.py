"""Image quality assessment capability."""
from __future__ import annotations

from typing import Any

from src.multimodal.parsers.json_parser import safe_extract_json
from src.multimodal.parsers.validators import clamp_confidence, validate_result_literal
from src.multimodal.prompts import image_quality_v1
from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import (
    ImageQualityAssessment,
    ImageQualityIssue,
    MultimodalRequest,
    MultimodalMessagePart,
)

CAPABILITY = "image_quality_assessment"
VERSION = image_quality_v1.VERSION

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "confidence": {"type": "number"},
        "issues": {"type": "array"},
        "recommended_action": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["usable", "confidence", "recommended_action", "reason"],
}

_VALID_ISSUE_TYPES = {
    "blur", "low_light", "overexposure", "occlusion",
    "wrong_angle", "too_far", "too_close", "background_noise", "unknown",
}
_VALID_SEVERITIES = {"low", "medium", "high"}


def _parse_issues(raw: list) -> list[ImageQualityIssue]:
    issues = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        issue_type = item.get("issue_type", "unknown")
        if issue_type not in _VALID_ISSUE_TYPES:
            issue_type = "unknown"
        severity = item.get("severity", "low")
        if severity not in _VALID_SEVERITIES:
            severity = "low"
        issues.append(ImageQualityIssue(
            issue_type=issue_type,
            severity=severity,
            description=str(item.get("description", "")),
        ))
    return issues


def _parse_action(raw: Any) -> str:
    if raw in ("proceed", "retake", "manual_review"):
        return raw
    return "manual_review"


def assess_image_quality(
    provider: MultimodalProvider,
    image_path: str,
    expected_angle: str | None = None,
) -> ImageQualityAssessment:
    """Run image quality assessment on a single image."""
    prompt_text = image_quality_v1.build_prompt(expected_angle=expected_angle)

    request = MultimodalRequest(
        capability=CAPABILITY,
        prompt_version=VERSION,
        messages=[
            MultimodalMessagePart(type="image", image_path=image_path),
            MultimodalMessagePart(type="text", text=prompt_text),
        ],
        response_schema_name="ImageQualityAssessment",
        response_schema=RESPONSE_SCHEMA,
    )

    raw_response = provider.generate(request)
    parsed = safe_extract_json(raw_response.raw_text, fallback={})

    usable = bool(parsed.get("usable", False))
    confidence = clamp_confidence(parsed.get("confidence", 0.0))
    issues = _parse_issues(parsed.get("issues", []))
    action = _parse_action(parsed.get("recommended_action"))
    reason = str(parsed.get("reason", ""))

    # Safety: if issues present with high severity, force not usable
    if any(i.severity == "high" for i in issues):
        usable = False
        if action == "proceed":
            action = "manual_review"

    return ImageQualityAssessment(
        usable=usable,
        confidence=confidence,
        issues=issues,
        recommended_action=action,
        reason=reason,
    )
