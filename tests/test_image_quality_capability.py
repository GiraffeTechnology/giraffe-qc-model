"""Tests for image quality assessment capability."""
from __future__ import annotations

import json
import os
import pytest
import tempfile


def _make_mock_provider(response_json: dict):
    """Create a mock provider that returns a specific JSON response."""
    from src.multimodal.providers.mock_provider import MockProvider

    class CustomMockProvider(MockProvider):
        def generate(self, request):
            from src.multimodal.types import MultimodalRawResponse
            raw_text = json.dumps(response_json)
            return MultimodalRawResponse(
                provider="mock", model="mock-v1", raw_text=raw_text,
                raw_json=response_json, latency_ms=1, http_status=200,
            )
    return CustomMockProvider()


def _tmp_image() -> str:
    """Create a temporary fake image file."""
    f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    f.write(b"\xff\xd8\xff\xe0" + b"\x00" * 100)  # minimal JPEG-like bytes
    f.close()
    return f.name


def test_assess_image_quality_proceed(monkeypatch):
    img = _tmp_image()
    try:
        provider = _make_mock_provider({
            "usable": True,
            "confidence": 0.95,
            "issues": [],
            "recommended_action": "proceed",
            "reason": "Image is clear.",
        })
        from src.multimodal.capabilities.image_quality import assess_image_quality
        result = assess_image_quality(provider, img)
        assert result.usable is True
        assert result.recommended_action == "proceed"
    finally:
        os.unlink(img)


def test_assess_image_quality_blur(monkeypatch):
    img = _tmp_image()
    try:
        provider = _make_mock_provider({
            "usable": False,
            "confidence": 0.3,
            "issues": [{"issue_type": "blur", "severity": "high", "description": "Image is blurry"}],
            "recommended_action": "retake",
            "reason": "Too blurry.",
        })
        from src.multimodal.capabilities.image_quality import assess_image_quality
        result = assess_image_quality(provider, img)
        assert result.usable is False
        assert result.recommended_action in ("retake", "manual_review")
        assert len(result.issues) == 1
    finally:
        os.unlink(img)


def test_high_severity_issue_forces_not_usable(monkeypatch):
    img = _tmp_image()
    try:
        # Model says usable=True but issue severity=high → should force usable=False
        provider = _make_mock_provider({
            "usable": True,
            "confidence": 0.5,
            "issues": [{"issue_type": "blur", "severity": "high", "description": "Severe blur"}],
            "recommended_action": "proceed",
            "reason": "Somewhat OK.",
        })
        from src.multimodal.capabilities.image_quality import assess_image_quality
        result = assess_image_quality(provider, img)
        assert result.usable is False
        assert result.recommended_action != "proceed"
    finally:
        os.unlink(img)
