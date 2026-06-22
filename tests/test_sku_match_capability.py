"""Tests for SKU match capability."""
from __future__ import annotations

import json
import os
import tempfile


def _make_custom_mock(response_json: dict):
    from src.multimodal.providers.mock_provider import MockProvider
    class CM(MockProvider):
        def generate(self, request):
            from src.multimodal.types import MultimodalRawResponse
            return MultimodalRawResponse(
                provider="mock", model="mock-v1",
                raw_text=json.dumps(response_json), raw_json=response_json,
                latency_ms=1, http_status=200,
            )
    return CM()


def _tmp_image() -> str:
    f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    f.write(b"\xff\xd8" + b"\x00" * 50)
    f.close()
    return f.name


def test_sku_match_proceed():
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "matched": True,
            "top_candidates": [{"sku_id": "sku1", "standard_id": "std1", "score": 0.95, "reason": "match"}],
            "recommended_action": "proceed",
            "confidence": 0.95,
        })
        from src.multimodal.capabilities.sku_match import match_sku
        result = match_sku(provider, img, [], sku_id="sku1", standard_id="std1")
        assert result.matched is True
        assert result.recommended_action == "proceed"
    finally:
        os.unlink(img)


def test_sku_match_wrong_sku():
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "matched": False,
            "top_candidates": [],
            "recommended_action": "wrong_sku",
            "confidence": 0.2,
        })
        from src.multimodal.capabilities.sku_match import match_sku
        result = match_sku(provider, img, [], sku_id="sku1", standard_id="std1")
        assert result.matched is False
        assert result.recommended_action == "wrong_sku"
    finally:
        os.unlink(img)
