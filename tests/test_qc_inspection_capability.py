"""Tests for QC inspection capability."""
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


QC_POINTS = [
    {"qc_point_id": "p1", "qc_point_code": "C001", "name": "Surface", "description": "Check surface"},
    {"qc_point_id": "p2", "qc_point_code": "C002", "name": "Label", "description": "Check label"},
]
CONTEXT = {"tenant_id": "t1", "sku_id": "s1", "standard_id": "std1", "inspection_id": "i1"}


def test_qc_inspection_all_pass():
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "overall_result": "pass",
            "confidence": 0.92,
            "summary": "All pass",
            "items": [
                {"qc_point_id": "p1", "qc_point_code": "C001", "name": "Surface", "result": "pass", "confidence": 0.95, "reason": "OK", "evidence": {}},
                {"qc_point_id": "p2", "qc_point_code": "C002", "name": "Label", "result": "pass", "confidence": 0.92, "reason": "OK", "evidence": {}},
            ],
        })
        from src.multimodal.capabilities.qc_inspection import run_qc_inspection
        result = run_qc_inspection(provider, [], img, QC_POINTS, CONTEXT)
        assert result.overall_result == "pass"
        assert all(item.result == "pass" for item in result.items)
    finally:
        os.unlink(img)


def test_hallucinated_ids_rejected():
    """Items with IDs not in the valid set must be rejected."""
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "overall_result": "pass",
            "confidence": 0.9,
            "summary": "pass",
            "items": [
                {"qc_point_id": "hallucinated_id_xyz", "qc_point_code": "X", "name": "X", "result": "pass", "confidence": 0.9, "reason": "X", "evidence": {}},
                {"qc_point_id": "p1", "qc_point_code": "C001", "name": "Surface", "result": "pass", "confidence": 0.9, "reason": "OK", "evidence": {}},
            ],
        })
        from src.multimodal.capabilities.qc_inspection import run_qc_inspection
        result = run_qc_inspection(provider, [], img, QC_POINTS, CONTEXT)
        ids = [item.qc_point_id for item in result.items]
        assert "hallucinated_id_xyz" not in ids
    finally:
        os.unlink(img)


def test_missing_ids_filled_as_review_required():
    """QC point IDs not returned by model must be filled as review_required."""
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "overall_result": "pass",
            "confidence": 0.9,
            "summary": "partial",
            "items": [
                {"qc_point_id": "p1", "qc_point_code": "C001", "name": "Surface", "result": "pass", "confidence": 0.9, "reason": "OK", "evidence": {}},
                # p2 missing from model output
            ],
        })
        from src.multimodal.capabilities.qc_inspection import run_qc_inspection
        result = run_qc_inspection(provider, [], img, QC_POINTS, CONTEXT)
        ids = {item.qc_point_id: item for item in result.items}
        assert "p2" in ids
        assert ids["p2"].result == "review_required"
    finally:
        os.unlink(img)


def test_fail_item_makes_overall_fail():
    """If any item fails, overall must be fail."""
    img = _tmp_image()
    try:
        provider = _make_custom_mock({
            "overall_result": "pass",  # model claims pass but items say fail
            "confidence": 0.5,
            "summary": "x",
            "items": [
                {"qc_point_id": "p1", "qc_point_code": "C001", "name": "Surface", "result": "fail", "confidence": 0.3, "reason": "defect", "evidence": {}},
                {"qc_point_id": "p2", "qc_point_code": "C002", "name": "Label", "result": "pass", "confidence": 0.9, "reason": "OK", "evidence": {}},
            ],
        })
        from src.multimodal.capabilities.qc_inspection import run_qc_inspection
        result = run_qc_inspection(provider, [], img, QC_POINTS, CONTEXT)
        assert result.overall_result == "fail"
    finally:
        os.unlink(img)


def test_invalid_json_returns_review_required():
    """Invalid model output must result in all items being review_required."""
    img = _tmp_image()
    try:
        from src.multimodal.providers.mock_provider import MockProvider
        class BadMock(MockProvider):
            def generate(self, request):
                from src.multimodal.types import MultimodalRawResponse
                return MultimodalRawResponse(
                    provider="mock", model="mock-v1",
                    raw_text="THIS IS NOT JSON AT ALL !!!",
                    http_status=200, latency_ms=1,
                )
        from src.multimodal.capabilities.qc_inspection import run_qc_inspection
        result = run_qc_inspection(BadMock(), [], img, QC_POINTS, CONTEXT)
        # All items should be review_required since no valid JSON was returned
        for item in result.items:
            assert item.result == "review_required"
    finally:
        os.unlink(img)
