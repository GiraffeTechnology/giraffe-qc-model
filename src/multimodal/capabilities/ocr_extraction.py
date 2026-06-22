"""OCR extraction capability."""
from __future__ import annotations

from src.multimodal.parsers.json_parser import safe_extract_json
from src.multimodal.parsers.validators import clamp_confidence
from src.multimodal.prompts import ocr_extraction_v1
from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import (
    MultimodalMessagePart,
    MultimodalRequest,
    OCRExtractionResult,
)

CAPABILITY = "ocr_extraction"
VERSION = ocr_extraction_v1.VERSION

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "detected_text": {"type": "array"},
        "labels": {"type": "array"},
        "confidence": {"type": "number"},
        "issues": {"type": "array"},
    },
    "required": ["detected_text", "confidence"],
}


def extract_ocr(
    provider: MultimodalProvider,
    image_path: str,
    expected_fields: list[str] | None = None,
) -> OCRExtractionResult:
    """Run OCR extraction on an image."""
    prompt_text = ocr_extraction_v1.build_prompt(expected_fields=expected_fields)

    request = MultimodalRequest(
        capability=CAPABILITY,
        prompt_version=VERSION,
        messages=[
            MultimodalMessagePart(type="image", image_path=image_path),
            MultimodalMessagePart(type="text", text=prompt_text),
        ],
        response_schema_name="OCRExtractionResult",
        response_schema=RESPONSE_SCHEMA,
    )

    raw = provider.generate(request)
    parsed = safe_extract_json(raw.raw_text, fallback={})

    return OCRExtractionResult(
        detected_text=[str(t) for t in parsed.get("detected_text", [])],
        labels=[l for l in parsed.get("labels", []) if isinstance(l, dict)],
        confidence=clamp_confidence(parsed.get("confidence", 0.0)),
        issues=[str(i) for i in parsed.get("issues", [])],
    )
