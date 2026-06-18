"""QWEN output parser for the QC inspection pipeline.

Extracts structured QwenInspectionOutput from raw model responses.
Fails closed: if parsing fails, returns review_required.
"""
from __future__ import annotations

import json
import re
from typing import List

from src.qwen.schema import (
    FallbackInfo,
    InspectionItemResult,
    QwenInspectionOutput,
)


def _extract_json_from_text(raw: str) -> str:
    """Extract JSON from raw text, handling markdown code blocks."""
    # Try to find JSON in markdown code block first
    md_pattern = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    match = md_pattern.search(raw)
    if match:
        return match.group(1)

    # Try to find bare JSON object
    json_pattern = re.compile(r"\{.*\}", re.DOTALL)
    match = json_pattern.search(raw)
    if match:
        return match.group(0)

    return raw.strip()


def _make_fail_closed(engine: str, reason: str = "parse_error") -> QwenInspectionOutput:
    """Return a fail-closed (review_required) result when parsing fails."""
    return QwenInspectionOutput(
        overall_result="review_required",
        engine=engine,
        model_name="unknown",
        confidence=0.0,
        items=[],
        fallback=FallbackInfo(used=True, reason=reason),
        summary=f"Inspection result could not be parsed: {reason}",
    )


def parse_qwen_output(
    raw: str,
    expected_qc_point_ids: List[str],
    engine: str,
) -> QwenInspectionOutput:
    """Parse raw QWEN model output into a structured QwenInspectionOutput.

    - Extracts JSON from markdown code blocks if needed
    - Validates all required keys
    - Rejects hallucinated QC point IDs not in expected_qc_point_ids
    - Fills missing QC points as review_required with confidence 0.0
    - Clamps confidence to [0, 1]
    - Fails closed (returns review_required) if parsing fails entirely

    Args:
        raw: Raw string output from the QWEN model
        expected_qc_point_ids: List of valid QC point IDs to validate against
        engine: Engine identifier (e.g., "cloud_qwen", "local_qwen_mnn")

    Returns:
        QwenInspectionOutput (may be fail-closed if parsing fails)
    """
    if not raw or not raw.strip():
        return _make_fail_closed(engine, reason="empty_response")

    try:
        json_str = _extract_json_from_text(raw)
        data = json.loads(json_str)
    except (json.JSONDecodeError, ValueError):
        return _make_fail_closed(engine, reason="json_parse_failed")

    if not isinstance(data, dict):
        return _make_fail_closed(engine, reason="response_not_dict")

    # Extract and validate required top-level keys
    overall_result = data.get("overall_result")
    if overall_result not in ("pass", "fail", "review_required"):
        return _make_fail_closed(engine, reason=f"invalid_overall_result: {overall_result!r}")

    raw_confidence = data.get("confidence", 0.0)
    try:
        confidence = float(raw_confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    # Clamp to [0, 1]
    confidence = max(0.0, min(1.0, confidence))

    model_name = str(data.get("model_name", engine))
    summary = str(data.get("summary", ""))

    # Parse items
    raw_items = data.get("items", [])
    if not isinstance(raw_items, list):
        raw_items = []

    # Build lookup of expected IDs for fast membership test
    expected_id_set = set(expected_qc_point_ids)

    parsed_items: dict[str, InspectionItemResult] = {}
    for item_data in raw_items:
        if not isinstance(item_data, dict):
            continue
        qc_point_id = item_data.get("qc_point_id", "")
        if not qc_point_id:
            continue

        # Reject hallucinated QC point IDs
        if expected_id_set and qc_point_id not in expected_id_set:
            continue

        item_result = item_data.get("result", "review_required")
        if item_result not in ("pass", "fail", "review_required"):
            item_result = "review_required"

        raw_item_conf = item_data.get("confidence", 0.0)
        try:
            item_conf = float(raw_item_conf)
        except (TypeError, ValueError):
            item_conf = 0.0
        item_conf = max(0.0, min(1.0, item_conf))

        parsed_items[qc_point_id] = InspectionItemResult(
            qc_point_id=qc_point_id,
            qc_point_code=str(item_data.get("qc_point_code", qc_point_id)),
            name=str(item_data.get("name", qc_point_id)),
            result=item_result,
            confidence=item_conf,
            reason=str(item_data.get("reason", "")),
            evidence=item_data.get("evidence", {}) if isinstance(item_data.get("evidence"), dict) else {},
        )

    # Fill missing QC points as review_required with confidence 0.0
    for qc_point_id in expected_qc_point_ids:
        if qc_point_id not in parsed_items:
            parsed_items[qc_point_id] = InspectionItemResult(
                qc_point_id=qc_point_id,
                qc_point_code=qc_point_id,
                name=qc_point_id,
                result="review_required",
                confidence=0.0,
                reason="QC point result not provided by model",
                evidence={},
            )

    items_list = list(parsed_items.values())

    fallback_data = data.get("fallback", {})
    if isinstance(fallback_data, dict):
        fallback = FallbackInfo(
            used=bool(fallback_data.get("used", False)),
            reason=fallback_data.get("reason"),
        )
    else:
        fallback = FallbackInfo(used=False)

    return QwenInspectionOutput(
        overall_result=overall_result,
        engine=engine,
        model_name=model_name,
        confidence=confidence,
        items=items_list,
        fallback=fallback,
        summary=summary,
    )
