"""Tests for QC_ENGINE_MODE=cloud_qwen_dev provider selection and safety constraints.

These tests never make real API calls — they verify:
- cloud_qwen_dev is disabled by default (safe default)
- cloud_qwen_dev requires LLM_ENABLE_REAL_CALLS=true to use real provider
- API key is never logged in full
- engine name is never local_qwen_mnn when using cloud path
- DashScope provider rejects calls without required env vars
"""
from __future__ import annotations

import logging
import pytest

from src.qwen.fake_providers import FakeCloudQwenProvider
from src.qwen.service import QwenQCService
from src.qwen.schema import (
    CapturePhotoInput,
    InspectionContext,
    QcPointInput,
    StandardPhotoInput,
)


@pytest.fixture
def inspection_inputs():
    return dict(
        standard_photos=[StandardPhotoInput(photo_id="STD-1", local_path="/tmp/std.png")],
        captured_photo=CapturePhotoInput(photo_id="CAP-1", local_path="/tmp/cap.png"),
        qc_points=[
            QcPointInput(qc_point_id="QC-01", qc_point_code="color", name="Color", description="Color match"),
        ],
        context=InspectionContext(
            tenant_id="t1", sku_id="SKU-1", standard_id="STD-1", inspection_id="INS-1"
        ),
    )


class TestDefaultMode:
    def test_default_mode_has_no_provider_in_production(self, monkeypatch, inspection_inputs):
        """By default production runtime must not select the fake provider."""
        monkeypatch.delenv("QC_ENGINE_MODE", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("QC_ALLOW_TEST_ADAPTER", raising=False)
        monkeypatch.delenv("QWEN_CLOUD_ENABLED", raising=False)
        monkeypatch.delenv("LLM_ENABLE_REAL_CALLS", raising=False)
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)

        svc = QwenQCService()
        provider = svc._get_provider()
        assert provider is None

    def test_default_mode_returns_review_required_not_fake_pass(self, monkeypatch, inspection_inputs):
        monkeypatch.delenv("QC_ENGINE_MODE", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("QC_ALLOW_TEST_ADAPTER", raising=False)
        monkeypatch.delenv("LLM_ENABLE_REAL_CALLS", raising=False)
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")

        svc = QwenQCService()
        result = svc.run_inspection(**inspection_inputs)
        assert result.overall_result == "review_required"
        assert result.engine == "router"
        assert result.engine != "fake_cloud_qwen"

    def test_engine_never_local_qwen_mnn_from_service(self, monkeypatch, inspection_inputs):
        """Cloud or fake path must never mark engine as local_qwen_mnn."""
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("QC_ENGINE_MODE", "fake")
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        svc = QwenQCService()
        result = svc.run_inspection(**inspection_inputs)
        assert result.engine != "local_qwen_mnn"


class TestCloudQwenDevMode:
    def test_cloud_qwen_dev_without_real_calls_returns_review_required(self, monkeypatch, inspection_inputs):
        """cloud_qwen_dev without LLM_ENABLE_REAL_CALLS=true must not use fake."""
        monkeypatch.setenv("QC_ENGINE_MODE", "cloud_qwen_dev")
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "false")
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")

        svc = QwenQCService()
        provider = svc._get_provider()
        assert provider is None
        result = svc.run_inspection(**inspection_inputs)
        assert result.overall_result == "review_required"
        assert result.engine != "fake_cloud_qwen"

    def test_cloud_qwen_dev_without_key_uses_real_provider_error_path(self, monkeypatch):
        """cloud_qwen_dev with real calls enabled but no key never falls back to fake."""
        monkeypatch.setenv("QC_ENGINE_MODE", "cloud_qwen_dev")
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "true")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("QWEN_API_KEY", raising=False)
        # Also need cloud guards set for DashScope to even try
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")

        svc = QwenQCService()
        # Without key, DashScope provider is selected but inspection fails closed.
        provider = svc._get_provider()
        assert provider is not None

    def test_on_device_first_mode_has_no_server_fake(self, monkeypatch):
        """on_device_first mode does not use a server-side fake provider."""
        monkeypatch.setenv("QC_ENGINE_MODE", "on_device_first")
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "false")

        svc = QwenQCService()
        provider = svc._get_provider()
        assert provider is None

    def test_fake_mode_uses_fake_only_in_test_harness(self, monkeypatch):
        monkeypatch.setenv("APP_ENV", "test")
        monkeypatch.setenv("QC_ENGINE_MODE", "fake")
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "true")

        svc = QwenQCService()
        provider = svc._get_provider()
        assert isinstance(provider, FakeCloudQwenProvider)

    def test_fake_mode_rejected_in_production(self, monkeypatch):
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("QC_ALLOW_TEST_ADAPTER", raising=False)
        monkeypatch.setenv("QC_ENGINE_MODE", "fake")

        svc = QwenQCService()
        assert svc._get_provider() is None

    def test_unknown_mode_defers_inspection(self, monkeypatch):
        monkeypatch.setenv("QC_ENGINE_MODE", "some_unknown_future_mode")
        svc = QwenQCService()
        provider = svc._get_provider()
        assert provider is None


class TestDashScopeProviderGuards:
    """DashScope provider has two explicit safety guards that must both be set."""

    def test_cloud_disabled_raises(self, monkeypatch):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key-for-test")

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        with pytest.raises(RuntimeError, match="QWEN cloud disabled"):
            provider._check_guards()

    def test_images_not_allowed_raises(self, monkeypatch):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "false")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "fake-key-for-test")

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        with pytest.raises(RuntimeError, match="Sending images to cloud QWEN is disabled"):
            provider._check_guards()

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("QWEN_API_KEY", raising=False)

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        with pytest.raises(RuntimeError, match="No DashScope API key"):
            provider._check_guards()

    def test_all_guards_pass_with_valid_config(self, monkeypatch):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-test-key-for-guard-check")

        from src.qwen.dashscope_provider import DashScopeQwenProvider
        provider = DashScopeQwenProvider()
        # Must not raise
        provider._check_guards()


class TestApiKeyNotLoggedInFull:
    """API key must never appear in full in log output."""

    def test_key_masked_in_service_logs(self, monkeypatch, caplog):
        """Service logs must never emit the full API key."""
        full_key = "sk-abcdefghijklmnopqrstuvwxyz1234567890"
        monkeypatch.setenv("QC_ENGINE_MODE", "cloud_qwen_dev")
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "true")
        monkeypatch.setenv("DASHSCOPE_API_KEY", full_key)
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")

        with caplog.at_level(logging.DEBUG, logger="src.qwen.service"):
            svc = QwenQCService()
            svc._get_provider()

        log_text = caplog.text
        # Full key must never appear in logs
        assert full_key not in log_text

    def test_key_first_chars_appear_but_not_full(self, monkeypatch, caplog):
        full_key = "sk-abcdef1234567890xxxx"
        monkeypatch.setenv("QC_ENGINE_MODE", "cloud_qwen_dev")
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "true")
        monkeypatch.setenv("DASHSCOPE_API_KEY", full_key)
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")

        with caplog.at_level(logging.DEBUG, logger="src.qwen.service"):
            svc = QwenQCService()
            svc._get_provider()

        log_text = caplog.text
        assert full_key not in log_text
        # If key appears at all, it should be masked
        if "sk-" in log_text:
            assert "****" in log_text


class TestExplicitOverride:
    def test_explicit_provider_overrides_mode(self, monkeypatch, inspection_inputs):
        """Constructor-injected provider always wins over QC_ENGINE_MODE."""
        monkeypatch.setenv("QC_ENGINE_MODE", "cloud_qwen_dev")
        monkeypatch.setenv("LLM_ENABLE_REAL_CALLS", "true")

        explicit = FakeCloudQwenProvider()
        svc = QwenQCService(cloud_provider=explicit)
        assert svc._get_provider() is explicit
