"""Report generation prompt — version 1."""
from __future__ import annotations

import json
from typing import Any

VERSION = "report-generation-v1"

SYSTEM_ROLE = (
    "You are a QC report writer. Generate a human-readable report strictly based on "
    "the provided structured QC result. Do not add new facts or change any result."
)

SAFETY_RULES = (
    "Rules:\n"
    "- Do NOT change pass/fail/review_required results.\n"
    "- Only summarize the provided structured data.\n"
    "- Do not introduce new observations or conclusions.\n"
    "- Write in both Chinese and English.\n"
    "- Return JSON only."
)

OUTPUT_SCHEMA = """{\n  \"report_zh\": \"...\",\n  \"report_en\": \"...\",\n  \"executive_summary_zh\": \"...\",\n  \"executive_summary_en\": \"...\"\n}"""


def build_prompt(inspection_result: dict[str, Any]) -> str:
    result_json = json.dumps(inspection_result, ensure_ascii=False, indent=2)
    return (
        f"{SYSTEM_ROLE}\n\n"
        f"Structured inspection result:\n{result_json}\n\n"
        f"{SAFETY_RULES}\n\n"
        f"Output schema:\n{OUTPUT_SCHEMA}"
    )
