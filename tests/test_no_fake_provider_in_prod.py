"""Production-safety tests for fake QWEN provider selection."""
from __future__ import annotations

from src.qwen.service import QwenQCService
from src.qwen.schema import CapturePhotoInput, InspectionContext, QcPointInput, StandardPhotoInput


def _inputs():
    return dict(
        standard_photos=[StandardPhotoInput(photo_id="std-1", local_path="/tmp/std.png")],
        captured_photo=CapturePhotoInput(photo_id="cap-1", local_path="/tmp/cap.png"),
        qc_points=[
            QcPointInput(
                qc_point_id="point-1",
                qc_point_code="COLOR",
                name="Color",
                description="Color must match standard",
            )
        ],
        context=InspectionContext(
            tenant_id="tenant-prod",
            sku_id="SKU-1",
            standard_id="STD-1",
            inspection_id="INS-1",
        ),
    )


def test_default_server_inspection_cannot_return_pass_through_fake_provider(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("QC_ALLOW_TEST_ADAPTER", raising=False)
    monkeypatch.delenv("QC_ENGINE_MODE", raising=False)
    monkeypatch.delenv("LLM_ENABLE_REAL_CALLS", raising=False)
    monkeypatch.delenv("QWEN_CLOUD_ENABLED", raising=False)

    result = QwenQCService().run_inspection(**_inputs())

    assert result.overall_result == "review_required"
    assert result.engine == "router"
    assert result.model_name == "none"


def test_explicit_test_env_allows_fake_provider(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("QC_ENGINE_MODE", "fake")
    monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")

    result = QwenQCService().run_inspection(**_inputs())

    assert result.overall_result == "pass"
    assert result.engine == "fake_cloud_qwen"


def test_cloud_qwen_dev_real_calls_disabled_returns_review_required(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("QC_ALLOW_TEST_ADAPTER", raising=False)
    monkeypatch.setenv("QC_ENGINE_MODE", "cloud_qwen_dev")
    monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "false")
    monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")

    result = QwenQCService().run_inspection(**_inputs())

    assert result.overall_result == "review_required"
    assert result.engine != "fake_cloud_qwen"


def test_backend_proxy_missing_api_key_returns_review_required(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("QC_ALLOW_TEST_ADAPTER", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("QC_ENGINE_MODE", "backend_proxy")
    monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "true")
    monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
    monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")

    result = QwenQCService().run_inspection(**_inputs())

    assert result.overall_result == "review_required"
    assert result.engine == "cloud_qwen"
    assert result.fallback.used is True
    assert "No DashScope API key" in (result.fallback.reason or "")


def test_deterministic_adapter_route_not_mounted_in_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("QC_ALLOW_TEST_ADAPTER", raising=False)

    from fastapi.testclient import TestClient
    from src.api.main import app

    resp = TestClient(app).post("/test/qc/inspect", json={})
    assert resp.status_code in (404, 403)
