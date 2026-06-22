"""Tests for defect grounding capability."""
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


def test_defect_grounding_with_valid_bbox():
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "defects": [{
                "qc_point_id": "p1",
                "defect_type": "scratch",
                "severity": "major",
                "visual_regions": [{"label": "scratch", "bbox": [0.1, 0.2, 0.5, 0.6], "confidence": 0.85, "description": "visible scratch"}],
                "confidence": 0.85,
                "description_zh": "划痕",
                "description_en": "scratch",
            }]
        })
        from src.multimodal.capabilities.defect_grounding import ground_defects
        results = ground_defects(provider, img, None, [{"qc_point_id": "p1", "result": "fail"}])
        assert len(results) == 1
        assert results[0].visual_regions[0].bbox == [0.1, 0.2, 0.5, 0.6]
    finally:
        os.unlink(img)


def test_invalid_bbox_rejected():
    """Bbox outside 0-1 range must be rejected (set to None)."""
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "defects": [{
                "qc_point_id": "p1",
                "defect_type": "scratch",
                "severity": "minor",
                "visual_regions": [{"label": "x", "bbox": [100, 200, 500, 600], "confidence": 0.5, "description": "x"}],
                "confidence": 0.5,
                "description_zh": "",
                "description_en": "",
            }]
        })
        from src.multimodal.capabilities.defect_grounding import ground_defects
        results = ground_defects(provider, img, None, [{"qc_point_id": "p1"}])
        assert results[0].visual_regions[0].bbox is None
    finally:
        os.unlink(img)


def test_empty_items_returns_empty():
    img = _tmp_image()
    try:
        from src.multimodal.providers.mock_provider import MockProvider
        from src.multimodal.capabilities.defect_grounding import ground_defects
        results = ground_defects(MockProvider(), img, None, [])
        assert results == []
    finally:
        os.unlink(img)
