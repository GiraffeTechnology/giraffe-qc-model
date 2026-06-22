"""JSON extraction from model raw text output."""
from __future__ import annotations

import json
import re

from src.multimodal.errors import MultimodalParseError


def extract_json(raw_text: str) -> dict:
    """Extract and parse JSON from model output, handling markdown fences."""
    cleaned = re.sub(r"```(?:json)?", "", raw_text, flags=re.IGNORECASE).strip(" \n`")
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise MultimodalParseError(f"Cannot extract JSON from model output: {raw_text[:200]!r}")


def safe_extract_json(raw_text: str, fallback: dict | None = None) -> dict:
    """Like extract_json but returns fallback instead of raising."""
    try:
        return extract_json(raw_text)
    except MultimodalParseError:
        return fallback or {}
