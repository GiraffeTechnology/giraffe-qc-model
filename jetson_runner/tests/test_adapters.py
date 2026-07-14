"""De-mock labeling, mock/real adapter switching, and runtime fail-closed behavior.

Covers WS5's core requirement: JETSON_MOCK_MODE must actually gate which
inference path runs, must be impossible under APP_ENV=production, mock
inference must be unmistakably logged, and a real adapter that isn't ready
must fail closed (reject /infer with runtime_not_ready) rather than silently
falling back to mock or letting a bad call through.
"""
from __future__ import annotations

import logging

import pytest

from jetson_runner.app.adapters.base import InferenceAdapter
from jetson_runner.app.adapters.mnn_adapter import MnnVlmAdapter
from jetson_runner.app.adapters.mock_adapter import MockInferenceAdapter
from jetson_runner.app.config import MockModeNotAllowedInProduction, RunnerConfig
from jetson_runner.app.identity import generate_identity
from jetson_runner.app.main import InferenceRejected, JetsonRunnerService
from jetson_runner.app.pad_client import MockPad
from src.qc_model.jetson.contract import InferenceResponse, PerPointResult


def _request(job="j1"):
    return {
        "job_id": job,
        "standard_revision_id": "r1",
        "image": "frame://x",
        "detection_points": [{"point_code": "cp1", "label": "core centered"}],
    }


# ── production lock (config.py) ──────────────────────────────────────────────


def test_mock_mode_true_raises_under_app_env_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(MockModeNotAllowedInProduction):
        RunnerConfig(mock_mode=True)


def test_mock_mode_defaults_false_under_app_env_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("JETSON_MOCK_MODE", raising=False)
    cfg = RunnerConfig()
    assert cfg.mock_mode is False


def test_mock_mode_defaults_false_outside_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("JETSON_MOCK_MODE", raising=False)
    monkeypatch.delenv("XAVIER_INFERENCE_MODE", raising=False)
    cfg = RunnerConfig()
    assert cfg.mock_mode is False


# ── adapter selection ─────────────────────────────────────────────────────────


def test_service_selects_mock_adapter_when_mock_mode_true():
    svc = JetsonRunnerService(RunnerConfig(mock_mode=True), identity=generate_identity("jetson-test"))
    assert isinstance(svc.adapter, MockInferenceAdapter)
    assert svc.adapter.adapter_name == "mock"


def test_service_selects_mnn_adapter_when_mock_mode_false(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")  # allowed outside production too
    svc = JetsonRunnerService(RunnerConfig(mock_mode=False), identity=generate_identity("jetson-test"))
    assert isinstance(svc.adapter, MnnVlmAdapter)
    assert svc.adapter.adapter_name == "mnn"


# ── mock-mode labeling ────────────────────────────────────────────────────────


def test_mock_inference_logs_unmistakable_warning(caplog):
    svc = JetsonRunnerService(RunnerConfig(mock_mode=True), identity=generate_identity("jetson-test"))
    pad = MockPad("pad-1")
    pad.pair_over_usb(svc.pairing)
    with caplog.at_level(logging.WARNING, logger="jetson_runner"):
        pad.call(svc, _request())
    assert any("MOCK INFERENCE — NOT REAL QC JUDGMENT" in r.message for r in caplog.records)


def test_real_adapter_path_does_not_log_mock_warning(caplog):
    class _FakeReadyAdapter(InferenceAdapter):
        @property
        def adapter_name(self) -> str:
            return "fake"

        @property
        def model_name(self) -> str:
            return "fake-model"

        def is_ready(self) -> bool:
            return True

        def run_inference(self, payload: dict) -> InferenceResponse:
            return InferenceResponse(
                job_id=payload["job_id"],
                per_point_results=[PerPointResult(point_code="cp1", result="pass", confidence=0.9)],
            )

    svc = JetsonRunnerService(
        RunnerConfig(mock_mode=False), identity=generate_identity("jetson-test"), adapter=_FakeReadyAdapter()
    )
    pad = MockPad("pad-1")
    pad.pair_over_usb(svc.pairing)
    with caplog.at_level(logging.WARNING, logger="jetson_runner"):
        resp = pad.call(svc, _request())
    assert resp["per_point_results"][0]["result"] == "pass"
    assert not any("MOCK INFERENCE" in r.message for r in caplog.records)


# ── fail-closed on a not-ready real adapter ──────────────────────────────────


def test_real_adapter_not_ready_rejects_infer_without_calling_backend():
    calls = []

    class _FakeNotReadyAdapter(InferenceAdapter):
        @property
        def adapter_name(self) -> str:
            return "fake"

        @property
        def model_name(self) -> str:
            return "fake-model"

        def is_ready(self) -> bool:
            return False

        def run_inference(self, payload: dict) -> InferenceResponse:
            calls.append(payload)
            raise AssertionError("must not be called when not ready")

    svc = JetsonRunnerService(
        RunnerConfig(mock_mode=False), identity=generate_identity("jetson-test"), adapter=_FakeNotReadyAdapter()
    )
    pad = MockPad("pad-1")
    pad.pair_over_usb(svc.pairing)
    with pytest.raises(InferenceRejected) as exc:
        pad.call(svc, _request())
    assert exc.value.reason == "runtime_not_ready"
    assert calls == []
