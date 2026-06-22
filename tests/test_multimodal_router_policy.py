"""Tests for CapabilityRouter policy: fail-closed, cloud fallback, image validation."""
from __future__ import annotations

import json
import os
import tempfile


def _tmp_image() -> str:
    f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
    f.write(b"\xff\xd8" + b"\x00" * 50)
    f.close()
    return f.name


def _qc_points():
    return [
        {"qc_point_id": "p1", "qc_point_code": "C001", "name": "Surface", "description": "Check"},
        {"qc_point_id": "p2", "qc_point_code": "C002", "name": "Label", "description": "Check"},
    ]


def _context():
    from src.multimodal.router import RoutingContext
    return RoutingContext(tenant_id="t1", sku_id="s1", standard_id="std1", inspection_id="i1")


def test_missing_image_returns_review_required():
    """Missing captured image must never produce pass."""
    from src.multimodal.providers.mock_provider import MockProvider
    from src.multimodal.router import CapabilityRouter

    router = CapabilityRouter(provider=MockProvider())
    result = router.run(
        standard_image_paths=[],
        captured_image_path="/nonexistent/image.jpg",
        qc_points=_qc_points(),
        context=_context(),
    )
    assert result.inspection.overall_result == "review_required"
    assert result.fallback_reason == "captured_image_not_found"


def test_local_fail_is_final_by_default(monkeypatch):
    """Simulated local fail must stay fail when QC_CLOUD_CAN_OVERRIDE_LOCAL_FAIL=false."""
    monkeypatch.setenv("QC_CLOUD_CAN_OVERRIDE_LOCAL_FAIL", "false")
    img = _tmp_image()
    try:
        from src.multimodal.providers.mock_provider import MockProvider
        from src.multimodal.router import CapabilityRouter

        router = CapabilityRouter(provider=MockProvider())
        result = router.run(
            standard_image_paths=[],
            captured_image_path=img,
            qc_points=_qc_points(),
            context=_context(),
            simulated_local_result="fail",
        )
        assert result.inspection.overall_result == "review_required"
        assert result.fallback_reason == "local_fail_is_final"
    finally:
        os.unlink(img)


def test_unusable_image_stops_inspection(monkeypatch):
    """If image quality assessment returns unusable, do not proceed to inspection."""
    img = _tmp_image()
    try:
        from src.multimodal.providers.mock_provider import MockProvider

        class UnusableMock(MockProvider):
            def generate(self, request):
                from src.multimodal.types import MultimodalRawResponse
                if request.capability == "image_quality_assessment":
                    resp = {"usable": False, "confidence": 0.1, "issues": [], "recommended_action": "retake", "reason": "blurry"}
                else:
                    resp = {"overall_result": "pass", "confidence": 0.9, "summary": "x", "items": []}
                return MultimodalRawResponse(provider="mock", model="mock-v1", raw_text=json.dumps(resp), http_status=200, latency_ms=1)

        from src.multimodal.router import CapabilityRouter
        router = CapabilityRouter(provider=UnusableMock())
        result = router.run(
            standard_image_paths=[],
            captured_image_path=img,
            qc_points=_qc_points(),
            context=_context(),
        )
        assert result.inspection.overall_result == "review_required"
        assert result.image_quality is not None
        assert result.image_quality.usable is False
    finally:
        os.unlink(img)


def test_no_real_api_call_by_default(monkeypatch):
    """Default registry must not make any real API calls."""
    monkeypatch.setenv("MULTIMODAL_ENABLE_REAL_CALLS", "false")
    monkeypatch.setenv("MULTIMODAL_PROVIDER", "qwen")

    from src.multimodal.providers.registry import get_provider
    from src.multimodal.providers.mock_provider import MockProvider

    p = get_provider()
    assert isinstance(p, MockProvider)
    # MockProvider.generate never touches network
