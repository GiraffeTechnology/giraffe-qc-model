"""Tests for OCR extraction capability."""
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


def test_ocr_extraction_basic():
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "detected_text": ["SN12345", "LOT: ABC"],
            "labels": [{"field": "serial_number", "value": "SN12345", "confidence": 0.98}],
            "confidence": 0.95,
            "issues": [],
        })
        from src.multimodal.capabilities.ocr_extraction import extract_ocr
        result = extract_ocr(provider, img)
        assert "SN12345" in result.detected_text
        assert result.confidence > 0.9
    finally:
        os.unlink(img)


def test_ocr_low_confidence_has_issues():
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "detected_text": ["???"],
            "labels": [],
            "confidence": 0.2,
            "issues": ["low_contrast_region"],
        })
        from src.multimodal.capabilities.ocr_extraction import extract_ocr
        result = extract_ocr(provider, img)
        assert result.confidence == 0.2
        assert "low_contrast_region" in result.issues
    finally:
        os.unlink(img)
