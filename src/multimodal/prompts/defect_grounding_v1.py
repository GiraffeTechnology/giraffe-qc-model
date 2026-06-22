"""Defect grounding prompt — version 1."""
from __future__ import annotations

import json
from typing import Any

VERSION = "defect-grounding-v1"

SYSTEM_ROLE = (
    "You are a defect localization engine. "
    "Locate and describe visible evidence for each failed or review-required QC point."
)

SAFETY_RULES = (
    "Rules:\n"
    "- Locate visible regions that support each fail or review_required result.\n"
    "- Use normalized coordinates from 0.0 to 1.0 (bbox: [x1, y1, x2, y2]).\n"
    "- If no reliable region can be identified, return empty visual_regions array and explain why.\n"
    "- Do not invent defects that are not visible.\n"
    "- Return JSON only."
)

OUTPUT_SCHEMA = """{\n  \"defects\": [\n    {\n      \"qc_point_id\": \"...\",\n      \"defect_type\": \"...\",\n      \"severity\": \"minor|major|critical|unknown\",\n      \"visual_regions\": [\n        {\n          \"label\": \"...\",\n          \"bbox\": [0.1, 0.2, 0.5, 0.6],\n          \"confidence\": 0.85,\n          \"description\": \"...\"\n        }\n      ],\n      \"confidence\": 0.85,\n      \"description_zh\": \"...\",\n      \"description_en\": \"...\"\n    }\n  ]\n}"""


def build_prompt(failed_items: list[dict[str, Any]]) -> str:
    items_json = json.dumps(failed_items, ensure_ascii=False, indent=2)
    return (
        f"{SYSTEM_ROLE}\n\n"
        f"Failed/review-required QC items:\n{items_json}\n\n"
        f"{SAFETY_RULES}\n\n"
        f"Output schema:\n{OUTPUT_SCHEMA}"
    )
