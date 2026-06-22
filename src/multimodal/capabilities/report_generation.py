"""Report generation capability."""
from __future__ import annotations

from src.multimodal.parsers.json_parser import safe_extract_json
from src.multimodal.prompts import report_generation_v1
from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import (
    MultimodalMessagePart,
    MultimodalRequest,
    QCInspectionResult,
    QCReport,
)

CAPABILITY = "report_generation"
VERSION = report_generation_v1.VERSION

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "report_zh": {"type": "string"},
        "report_en": {"type": "string"},
        "executive_summary_zh": {"type": "string"},
        "executive_summary_en": {"type": "string"},
    },
    "required": ["report_zh", "report_en", "executive_summary_zh", "executive_summary_en"],
}


def generate_report(
    provider: MultimodalProvider,
    inspection_result: QCInspectionResult,
) -> QCReport:
    """Generate a human-readable QC report from structured results.

    Report generation cannot change pass/fail/review results.
    """
    result_dict = inspection_result.model_dump(mode="json")
    prompt_text = report_generation_v1.build_prompt(inspection_result=result_dict)

    request = MultimodalRequest(
        capability=CAPABILITY,
        prompt_version=VERSION,
        messages=[MultimodalMessagePart(type="text", text=prompt_text)],
        response_schema_name="QCReport",
        response_schema=RESPONSE_SCHEMA,
    )

    raw = provider.generate(request)
    parsed = safe_extract_json(raw.raw_text, fallback={})

    return QCReport(
        report_zh=str(parsed.get("report_zh", "")),
        report_en=str(parsed.get("report_en", "")),
        executive_summary_zh=str(parsed.get("executive_summary_zh", "")),
        executive_summary_en=str(parsed.get("executive_summary_en", "")),
    )
