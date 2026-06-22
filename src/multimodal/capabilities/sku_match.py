"""SKU matching capability."""
from __future__ import annotations

from src.multimodal.parsers.json_parser import safe_extract_json
from src.multimodal.parsers.validators import clamp_confidence
from src.multimodal.prompts import sku_match_v1
from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import (
    MultimodalMessagePart,
    MultimodalRequest,
    SkuCandidate,
    SkuMatchResult,
)

CAPABILITY = "sku_match"
VERSION = sku_match_v1.VERSION

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "matched": {"type": "boolean"},
        "top_candidates": {"type": "array"},
        "recommended_action": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["matched", "recommended_action", "confidence"],
}

_VALID_ACTIONS = {"proceed", "manual_review", "wrong_sku"}


def match_sku(
    provider: MultimodalProvider,
    image_path: str,
    standard_image_paths: list[str],
    sku_id: str = "",
    standard_id: str = "",
) -> SkuMatchResult:
    """Run SKU match capability."""
    prompt_text = sku_match_v1.build_prompt(sku_id=sku_id, standard_id=standard_id)

    messages = []
    for p in standard_image_paths:
        messages.append(MultimodalMessagePart(type="image", image_path=p))
    messages.append(MultimodalMessagePart(type="image", image_path=image_path))
    messages.append(MultimodalMessagePart(type="text", text=prompt_text))

    request = MultimodalRequest(
        capability=CAPABILITY,
        prompt_version=VERSION,
        messages=messages,
        response_schema_name="SkuMatchResult",
        response_schema=RESPONSE_SCHEMA,
    )

    raw = provider.generate(request)
    parsed = safe_extract_json(raw.raw_text, fallback={})

    matched = bool(parsed.get("matched", False))
    confidence = clamp_confidence(parsed.get("confidence", 0.0))
    action = parsed.get("recommended_action", "manual_review")
    if action not in _VALID_ACTIONS:
        action = "manual_review"

    candidates = []
    for c in parsed.get("top_candidates", []):
        if isinstance(c, dict):
            candidates.append(SkuCandidate(
                sku_id=str(c.get("sku_id", sku_id)),
                standard_id=str(c.get("standard_id", standard_id)),
                score=clamp_confidence(c.get("score", 0.0)),
                reason=str(c.get("reason", "")),
            ))

    return SkuMatchResult(
        matched=matched,
        top_candidates=candidates,
        recommended_action=action,
        confidence=confidence,
    )
