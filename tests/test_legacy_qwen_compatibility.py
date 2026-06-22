"""Tests that legacy Qwen service still works alongside new multimodal layer."""
from __future__ import annotations

import pytest


def _make_qc_points():
    from src.qwen.schema import QcPointInput
    return [
        QcPointInput(qc_point_id="p1", qc_point_code="C001", name="Surface", description="check"),
    ]


def _make_standard_photos():
    from src.qwen.schema import StandardPhotoInput
    return [StandardPhotoInput(photo_id="ph1", local_path="/nonexistent/std.jpg")]


def _make_capture_photo():
    from src.qwen.schema import CapturePhotoInput
    return CapturePhotoInput(photo_id="cap1", local_path="/nonexistent/cap.jpg")


def _make_context():
    from src.qwen.schema import InspectionContext
    return InspectionContext(tenant_id="t1", sku_id="s1", standard_id="std1", inspection_id="i1")


def test_legacy_qwen_service_still_importable():
    """QwenQCService must still be importable."""
    from src.qwen.service import QwenQCService
    svc = QwenQCService()
    assert svc is not None


def test_legacy_qwen_service_run_inspection_fake_mode(monkeypatch):
    """QwenQCService must work in fake mode without real API calls."""
    monkeypatch.setenv("QC_ENGINE_MODE", "fake")
    monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "false")

    from src.qwen.service import QwenQCService
    svc = QwenQCService()
    result = svc.run_inspection(
        standard_photos=_make_standard_photos(),
        captured_photo=_make_capture_photo(),
        qc_points=_make_qc_points(),
        context=_make_context(),
    )
    assert result.overall_result in ("pass", "fail", "review_required")
    assert result.engine is not None


def test_legacy_qwen_schema_imports():
    from src.qwen.schema import (
        CapturePhotoInput,
        FallbackInfo,
        InspectionContext,
        InspectionItemResult,
        QcPointInput,
        QwenInspectionOutput,
        StandardPhotoInput,
    )
    # All imports must succeed
    assert QwenInspectionOutput is not None


def test_new_multimodal_service_alongside_legacy(monkeypatch):
    """New MultimodalQCService must coexist with QwenQCService."""
    monkeypatch.setenv("MULTIMODAL_ENABLE_REAL_CALLS", "false")
    monkeypatch.setenv("MULTIMODAL_PROVIDER", "mock")

    from src.multimodal.service import MultimodalQCService
    from src.qwen.service import QwenQCService

    mm_svc = MultimodalQCService()
    legacy_svc = QwenQCService()

    assert mm_svc is not None
    assert legacy_svc is not None


def test_qwen_router_imports():
    from src.qwen.router import QwenRouter
    router = QwenRouter()
    assert router is not None


def test_qwen_base_imports():
    from src.qwen.base import QwenQCProvider
    assert QwenQCProvider is not None
