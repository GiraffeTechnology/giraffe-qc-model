"""QC inspection capability."""
from __future__ import annotations

from typing import Any

from src.multimodal.parsers.json_parser import safe_extract_json
from src.multimodal.parsers.validators import (
    clamp_confidence,
    fill_missing_ids,
    reject_hallucinated_ids,
    validate_result_literal,
)
from src.multimodal.prompts import qc_inspection_v2
from src.multimodal.providers.base import MultimodalProvider
from src.multimodal.types import (
    MultimodalMessagePart,
    MultimodalRequest,
    QCEvidence,
    QCInspectionResult,
    QCItemResult,
)

CAPABILITY = "qc_inspection"
VERSION = qc_inspection_v2.VERSION

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "overall_result": {"type": "string"},
        "confidence": {"type": "number"},
        "summary": {"type": "string"},
        "items": {"type": "array"},
    },
    "required": ["overall_result", "confidence", "items"],
}


def _parse_items(
    raw_items: list[Any],
    valid_ids: set[str],
    qc_point_meta: dict[str, dict],
) -> list[QCItemResult]:
    cleaned = reject_hallucinated_ids(
        [i for i in raw_items if isinstance(i, dict)],
        valid_ids,
    )
    filled = fill_missing_ids(cleaned, valid_ids, reason="not_returned_by_model")

    results = []
    for item in filled:
        pid = item.get("qc_point_id", "")
        meta = qc_point_meta.get(pid, {})
        ev_raw = item.get("evidence", {}) or {}
        evidence = QCEvidence(
            standard_reference=str(ev_raw.get("standard_reference", "")),
            production_observation=str(ev_raw.get("production_observation", "")),
            model_reasoning_summary=str(ev_raw.get("model_reasoning_summary", "")),
        )
        results.append(QCItemResult(
            qc_point_id=pid,
            qc_point_code=item.get("qc_point_code") or meta.get("qc_point_code", ""),
            name=item.get("name") or meta.get("name", ""),
            result=validate_result_literal(item.get("result")),
            confidence=clamp_confidence(item.get("confidence", 0.0)),
            reason=str(item.get("reason", "")),
            evidence=evidence,
        ))
    return results


def _derive_overall(items: list[QCItemResult]) -> str:
    results = {i.result for i in items}
    if "fail" in results:
        return "fail"
    if "review_required" in results:
        return "review_required"
    return "pass"


def run_qc_inspection(
    provider: MultimodalProvider,
    standard_image_paths: list[str],
    captured_image_path: str,
    qc_points: list[dict[str, Any]],
    context: dict[str, Any],
) -> QCInspectionResult:
    """Run QC inspection capability against provider."""
    valid_ids = {p["qc_point_id"] for p in qc_points}
    qc_point_meta = {p["qc_point_id"]: p for p in qc_points}

    prompt_text = qc_inspection_v2.build_prompt(qc_points=qc_points, context=context)

    messages: list[MultimodalMessagePart] = []
    for p in standard_image_paths:
        messages.append(MultimodalMessagePart(type="image", image_path=p))
    messages.append(MultimodalMessagePart(type="image", image_path=captured_image_path))
    messages.append(MultimodalMessagePart(type="text", text=prompt_text))

    request = MultimodalRequest(
        capability=CAPABILITY,
        prompt_version=VERSION,
        messages=messages,
        response_schema_name="QCInspectionResult",
        response_schema=RESPONSE_SCHEMA,
    )

    raw = provider.generate(request)
    parsed = safe_extract_json(raw.raw_text, fallback={})

    items = _parse_items(
        parsed.get("items", []),
        valid_ids=valid_ids,
        qc_point_meta=qc_point_meta,
    )

    overall = validate_result_literal(parsed.get("overall_result"))
    # Enforce overall from items — never trust model's overall blindly
    derived = _derive_overall(items)
    if derived != overall:
        overall = derived

    return QCInspectionResult(
        overall_result=overall,
        engine="multimodal_qc",
        provider=raw.provider,
        model_name=raw.model,
        confidence=clamp_confidence(parsed.get("confidence", 0.0)),
        items=items,
        fallback={},
        summary=str(parsed.get("summary", "")),
        capability_versions={CAPABILITY: VERSION},
    )
