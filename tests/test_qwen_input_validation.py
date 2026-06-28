"""Input validation for cloud QWEN inspection."""
from __future__ import annotations

from src.qwen.dashscope_provider import DashScopeQwenProvider
from src.qwen.router import QwenRouter
from src.qwen.schema import CapturePhotoInput, InspectionContext, QcPointInput, StandardPhotoInput


def _point() -> QcPointInput:
    return QcPointInput(
        qc_point_id="point-1",
        qc_point_code="COLOR",
        name="Color",
        description="Color must match",
    )


def _context() -> InspectionContext:
    return InspectionContext(
        tenant_id="tenant-1",
        sku_id="SKU-1",
        standard_id="STD-1",
        inspection_id="INS-1",
    )


def _enable_cloud_guards(monkeypatch) -> None:
    monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
    monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")


def test_missing_standard_photo_returns_review_required(monkeypatch, tmp_path):
    _enable_cloud_guards(monkeypatch)
    capture = tmp_path / "capture.png"
    capture.write_bytes(b"fake-image")

    result = QwenRouter().route(
        standard_photos=[StandardPhotoInput(photo_id="std-1", local_path=str(tmp_path / "missing.png"))],
        captured_photo=CapturePhotoInput(photo_id="cap-1", local_path=str(capture)),
        qc_points=[_point()],
        context=_context(),
        cloud_provider=DashScopeQwenProvider(),
    )

    assert result.overall_result == "review_required"
    assert result.engine == "cloud_qwen"
    assert "Standard photo" in (result.fallback.reason or "")


def test_empty_standard_photos_returns_review_required(monkeypatch, tmp_path):
    _enable_cloud_guards(monkeypatch)
    capture = tmp_path / "capture.png"
    capture.write_bytes(b"fake-image")

    result = QwenRouter().route(
        standard_photos=[],
        captured_photo=CapturePhotoInput(photo_id="cap-1", local_path=str(capture)),
        qc_points=[_point()],
        context=_context(),
        cloud_provider=DashScopeQwenProvider(),
    )

    assert result.overall_result == "review_required"
    assert "No standard photos" in (result.fallback.reason or "")


def test_missing_capture_photo_returns_review_required(monkeypatch, tmp_path):
    _enable_cloud_guards(monkeypatch)
    standard = tmp_path / "standard.png"
    standard.write_bytes(b"fake-image")

    result = QwenRouter().route(
        standard_photos=[StandardPhotoInput(photo_id="std-1", local_path=str(standard))],
        captured_photo=CapturePhotoInput(photo_id="cap-1", local_path=str(tmp_path / "missing-cap.png")),
        qc_points=[_point()],
        context=_context(),
        cloud_provider=DashScopeQwenProvider(),
    )

    assert result.overall_result == "review_required"
    assert "Capture photo" in (result.fallback.reason or "")
