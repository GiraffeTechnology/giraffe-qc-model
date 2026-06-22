"""Defect grounding capability."""
from __future__ import annotations

from typing import Any

from src.multimodal.parsers.json_parser import safe_extract_json
from src.multimodal.parsers.validators import clamp_confidence, validate_bbox
from src.multimodal.prompts import defect_grounding_v1
from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import (
    DefectGroundingResult,
    MultimodalMessagePart,
    MultimodalRequest,
    VisualRegion,
)

CAPABILITY = "defect_grounding"
VERSION = defect_grounding_v1.VERSION

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"defects": {"type": "array"}},
    "required": ["defects"],
}

_VALID_SEVERITIES = {"minor", "major", "critical", "unknown"}


def _parse_regions(raw: list[Any]) -> list[VisualRegion]:
    regions = []
    for r in raw:
        if not isinstance(r, dict):
            continue
        bbox = validate_bbox(r.get("bbox"))
        regions.append(VisualRegion(
            label=str(r.get("label", "")),
            bbox=bbox,
            confidence=clamp_confidence(r.get("confidence", 0.0)),
            description=str(r.get("description", "")),
        ))
    return regions


def ground_defects(
    provider: MultimodalProvider,
    captured_image_path: str,
    standard_image_path: str | None,
    failed_items: list[dict[str, Any]],
) -> list[DefectGroundingResult]:
    """Localize defect evidence for fail/review_required items."""
    if not failed_items:
        return []

    prompt_text = defect_grounding_v1.build_prompt(failed_items=failed_items)
    messages: list[MultimodalMessagePart] = []
    if standard_image_path:
        messages.append(MultimodalMessagePart(type="image", image_path=standard_image_path))
    messages.append(MultimodalMessagePart(type="image", image_path=captured_image_path))
    messages.append(MultimodalMessagePart(type="text", text=prompt_text))

    request = MultimodalRequest(
        capability=CAPABILITY,
        prompt_version=VERSION,
        messages=messages,
        response_schema_name="DefectGroundingResult",
        response_schema=RESPONSE_SCHEMA,
    )

    raw = provider.generate(request)
    parsed = safe_extract_json(raw.raw_text, fallback={"defects": []})

    results = []
    for d in parsed.get("defects", []):
        if not isinstance(d, dict):
            continue
        severity = d.get("severity", "unknown")
        if severity not in _VALID_SEVERITIES:
            severity = "unknown"
        results.append(DefectGroundingResult(
            qc_point_id=str(d.get("qc_point_id", "")),
            defect_type=str(d.get("defect_type", "")),
            severity=severity,
            visual_regions=_parse_regions(d.get("visual_regions", [])),
            confidence=clamp_confidence(d.get("confidence", 0.0)),
            description_zh=str(d.get("description_zh", "")),
            description_en=str(d.get("description_en", "")),
        ))
    return results
