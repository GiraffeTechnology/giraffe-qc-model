"""QcResultParser — unified LLM output parser, Python counterpart of QcResultParser.kt.

Responsibilities:
1. Strip <think>…</think> blocks (Qwen3 thinking-mode defence).
2. Extract the first JSON object from noisy LLM output (markdown fences, prose).
3. Validate enum fields; return a fail-closed dict on any error — never raises.
"""
from __future__ import annotations

import json
import re

_VALID_OVERALL = frozenset({"pass", "needs_fix", "reject", "unknown"})
_VALID_SEVERITY = frozenset({"low", "medium", "high", "unknown"})


class QcResultParser:
    @staticmethod
    def strip_thinking_blocks(raw: str) -> str:
        """Remove all <think>…</think> sections (including multiline and multiple blocks)."""
        return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    @staticmethod
    def extract_json_str(text: str) -> str | None:
        """Return the first JSON object string found in *text*, or None."""
        # Prefer explicit markdown code fence
        md = re.search(r"```(?:json)?\s*\n?([\s\S]+?)\n?```", text, re.IGNORECASE)
        if md:
            return md.group(1).strip()
        # Fall back to outermost { … }
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return text[start : end + 1]
        return None

    @classmethod
    def parse(cls, raw: str) -> dict:
        """Parse raw LLM output into a normalised result dict.

        Always returns a dict. On any error, sets 'error' key and
        overall_result='unknown'. Never raises.
        """
        if not raw or not raw.strip():
            return {"error": "empty_response", "overall_result": "unknown"}

        stripped = cls.strip_thinking_blocks(raw)
        if not stripped:
            return {"error": "empty_after_stripping", "overall_result": "unknown"}

        json_str = cls.extract_json_str(stripped)
        if json_str is None:
            return {
                "error": "json_not_found",
                "overall_result": "unknown",
                "raw": raw[:200],
            }

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError as exc:
            return {
                "error": f"json_decode_error: {exc}",
                "overall_result": "unknown",
                "raw": json_str[:200],
            }

        if not isinstance(parsed, dict):
            return {"error": "not_a_dict", "overall_result": "unknown"}

        # Normalise overall_result
        result_val = parsed.get("overall_result", "unknown")
        if result_val not in _VALID_OVERALL:
            parsed["_original_overall_result"] = result_val
            parsed["overall_result"] = "unknown"

        # Normalise severity
        sev = parsed.get("severity", "unknown")
        if sev not in _VALID_SEVERITY:
            parsed["severity"] = "unknown"

        # Ensure deviations is always a list
        if not isinstance(parsed.get("deviations"), list):
            parsed["deviations"] = []

        return parsed
