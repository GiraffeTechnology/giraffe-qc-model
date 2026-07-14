"""Strict sandbox adapter around the production Qwen result parser."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from src.qwen.parser import parse_qwen_output


_THINK_BLOCK = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)
_THINK_OPEN = re.compile(r"<think\b[^>]*>", re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)
_INJECTION_MARKERS = (
    "ignore previous instructions",
    "reveal the system prompt",
    "<script",
    "tool_call",
)


class StrictOutputError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSandboxResult:
    sanitized_output: str
    parsed_result: dict[str, Any]
    verdict: str
    anomaly_notes: list[str]
    think_tags_stripped: bool


def sanitize_output(raw: str) -> tuple[str, bool]:
    if not isinstance(raw, str) or not raw.strip():
        raise StrictOutputError("empty_response")
    cleaned = "".join(ch for ch in raw if ch in "\n\r\t" or ord(ch) >= 32)
    stripped, count = _THINK_BLOCK.subn("", cleaned)
    opening = _THINK_OPEN.search(stripped)
    if opening:
        first_object = stripped.find("{", opening.end())
        if first_object < 0:
            raise StrictOutputError("unterminated_think_without_json")
        stripped = stripped[first_object:]
        count += 1
    return stripped.strip(), bool(count)


def _strict_object(raw: str) -> tuple[str, dict[str, Any]]:
    fenced = _FENCE.search(raw)
    candidate = fenced.group(1).strip() if fenced else raw.strip()
    decoder = json.JSONDecoder(object_pairs_hook=_reject_duplicate_keys)
    try:
        value, end = decoder.raw_decode(candidate)
    except json.JSONDecodeError as exc:
        raise StrictOutputError("json_parse_failed") from exc
    trailing = candidate[end:].strip()
    if trailing:
        raise StrictOutputError("trailing_content_rejected")
    if not isinstance(value, dict):
        raise StrictOutputError("response_not_object")
    canonical = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return canonical, value


def _reject_duplicate_keys(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise StrictOutputError(f"duplicate_key:{key}")
        value[key] = item
    return value


def parse_strict_sandbox_output(
    raw: str,
    *,
    expected_qc_point_ids: list[str],
    engine: str = "sandbox_server_vlm",
) -> ParsedSandboxResult:
    sanitized, think_stripped = sanitize_output(raw)
    lowered = sanitized.lower()
    if any(marker in lowered for marker in _INJECTION_MARKERS):
        raise StrictOutputError("injection_marker_rejected")
    canonical, _ = _strict_object(sanitized)
    parsed = parse_qwen_output(canonical, expected_qc_point_ids, engine)
    dumped = parsed.model_dump()
    anomalies: list[str] = []
    if parsed.fallback.used:
        anomalies.append(parsed.fallback.reason or "parser_fallback")
    if len(parsed.items) != len(expected_qc_point_ids):
        anomalies.append("point_count_mismatch")
    if any(item.result == "review_required" for item in parsed.items):
        anomalies.append("review_required")
    verdict = "pass" if parsed.overall_result == "pass" and not anomalies else "reject"
    return ParsedSandboxResult(
        sanitized_output=canonical,
        parsed_result=dumped,
        verdict=verdict,
        anomaly_notes=anomalies,
        think_tags_stripped=think_stripped,
    )


def fail_closed_result(reason: str, engine: str = "sandbox_server_vlm") -> ParsedSandboxResult:
    parsed = parse_qwen_output("", ["forced_failure"], engine)
    dumped = parsed.model_dump()
    dumped["fallback"] = {"used": True, "reason": reason}
    return ParsedSandboxResult(
        sanitized_output="",
        parsed_result=dumped,
        verdict="reject",
        anomaly_notes=[reason],
        think_tags_stripped=False,
    )
