"""QC inspection prompt — version 2."""
from __future__ import annotations

import json
from typing import Any

VERSION = "qc-inspection-v2"

SYSTEM_ROLE = (
    "You are a visual quality-control reasoning engine. "
    "Evaluate the provided product images against the standard reference photos and QC criteria."
)

SAFETY_RULES = (
    "Rules:\n"
    "- You are NOT allowed to invent QC point IDs. Only evaluate the listed QC points.\n"
    "- If uncertain, blurry, occluded, angle-mismatched, or visually ambiguous: return review_required.\n"
    "- Do not return pass unless the visual evidence is clear and unambiguous.\n"
    "- Overall result is pass only if ALL items pass.\n"
    "- Any fail → overall fail. Any review_required (with no fail) → overall review_required.\n"
    "- Confidence must be between 0.0 and 1.0.\n"
    "- Return JSON only. No markdown. No explanation outside the JSON."
)

OUTPUT_SCHEMA = """{\n  \"overall_result\": \"pass|fail|review_required\",\n  \"confidence\": 0.9,\n  \"model_name\": \"...\",\n  \"summary\": \"...\",\n  \"items\": [\n    {\n      \"qc_point_id\": \"<id from input>\",\n      \"qc_point_code\": \"<code>\",\n      \"name\": \"<name>\",\n      \"result\": \"pass|fail|review_required\",\n      \"confidence\": 0.9,\n      \"reason\": \"...\",\n      \"evidence\": {\n        \"standard_reference\": \"...\",\n        \"production_observation\": \"...\",\n        \"model_reasoning_summary\": \"...\"\n      }\n    }\n  ]\n}"""


def build_prompt(qc_points: list[dict[str, Any]], context: dict[str, Any]) -> str:
    points_json = json.dumps(qc_points, ensure_ascii=False, indent=2)
    ctx_str = f"SKU: {context.get('sku_id', '')}, Standard: {context.get('standard_id', '')}"
    return (
        f"{SYSTEM_ROLE}\n\n"
        f"Context: {ctx_str}\n\n"
        f"QC Points to evaluate:\n{points_json}\n\n"
        f"{SAFETY_RULES}\n\n"
        f"Output schema (strict JSON, include all listed qc_point_ids):\n{OUTPUT_SCHEMA}"
    )
