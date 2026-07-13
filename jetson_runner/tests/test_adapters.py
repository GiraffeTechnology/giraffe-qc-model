"""De-mock labeling, mock/real adapter switching, and the llama.cpp scaffold.

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
from jetson_runner.app.adapters.llama_cpp_adapter import LlamaCppInferenceAdapter
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


def test_mock_mode_defaults_true_outside_production(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("JETSON_MOCK_MODE", raising=False)
    cfg = RunnerConfig()
    assert cfg.mock_mode is True


# ── adapter selection ─────────────────────────────────────────────────────────


def test_service_selects_mock_adapter_when_mock_mode_true():
    svc = JetsonRunnerService(RunnerConfig(mock_mode=True), identity=generate_identity("jetson-test"))
    assert isinstance(svc.adapter, MockInferenceAdapter)
    assert svc.adapter.adapter_name == "mock"


def test_service_selects_llama_cpp_adapter_when_mock_mode_false(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")  # allowed outside production too
    svc = JetsonRunnerService(RunnerConfig(mock_mode=False), identity=generate_identity("jetson-test"))
    assert isinstance(svc.adapter, LlamaCppInferenceAdapter)
    assert svc.adapter.adapter_name == "llama_cpp"


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


# ── llama.cpp adapter: readiness ─────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeHttpClient:
    def __init__(self, *, health_status=200, post_response=None, get_raises=None, post_raises=None):
        self._health_status = health_status
        self._post_response = post_response
        self._get_raises = get_raises
        self._post_raises = post_raises

    def get(self, url, *, timeout):
        if self._get_raises:
            raise self._get_raises
        return _FakeResponse(self._health_status)

    def post(self, url, *, json, timeout):
        if self._post_raises:
            raise self._post_raises
        return self._post_response


def _adapter(**client_kwargs) -> LlamaCppInferenceAdapter:
    return LlamaCppInferenceAdapter(
        base_url="http://127.0.0.1:8080",
        model_name="qwen3.5-vl-2b-int4",
        http_client=_FakeHttpClient(**client_kwargs),
    )


def test_llama_cpp_is_ready_true_on_200():
    assert _adapter(health_status=200).is_ready() is True


def test_llama_cpp_is_ready_false_on_non_200():
    assert _adapter(health_status=503).is_ready() is False


def test_llama_cpp_is_ready_false_on_connection_error():
    assert _adapter(get_raises=ConnectionError("refused")).is_ready() is False


# ── llama.cpp adapter: inference parsing ─────────────────────────────────────


def _chat_response(content: str) -> _FakeResponse:
    return _FakeResponse(200, {"choices": [{"message": {"content": content}}]})


def test_llama_cpp_parses_valid_json_result():
    adapter = _adapter(post_response=_chat_response('{"result": "fail", "confidence": 0.8, "evidence": "crack visible"}'))
    resp = adapter.run_inference(_request())
    assert resp.per_point_results[0].result == "fail"
    assert resp.per_point_results[0].confidence == 0.8
    assert "crack visible" in resp.per_point_results[0].evidence


def test_llama_cpp_malformed_output_becomes_uncertain_not_a_crash():
    adapter = _adapter(post_response=_chat_response("I cannot determine this."))
    resp = adapter.run_inference(_request())
    assert resp.per_point_results[0].result == "uncertain"
    assert resp.per_point_results[0].confidence == 0.0


def test_llama_cpp_backend_unreachable_becomes_uncertain_not_a_crash():
    adapter = _adapter(post_raises=ConnectionError("refused"))
    resp = adapter.run_inference(_request())
    assert resp.per_point_results[0].result == "uncertain"


def test_llama_cpp_invalid_request_still_raises_validation_error():
    from pydantic import ValidationError

    adapter = _adapter(post_response=_chat_response("{}"))
    bad = {"job_id": "j1", "standard_revision_id": "r1", "image": "x", "detection_points": []}
    with pytest.raises(ValidationError):
        adapter.run_inference(bad)


def test_llama_cpp_multiple_points_independent_failure():
    """One point's parse failure must not affect a sibling point's result."""
    calls = {"n": 0}

    class _AlternatingClient(_FakeHttpClient):
        def post(self, url, *, json, timeout):
            calls["n"] += 1
            if calls["n"] == 1:
                return _chat_response('{"result": "pass", "confidence": 0.9, "evidence": "ok"}')
            return _chat_response("garbage, not json")

    adapter = LlamaCppInferenceAdapter(
        base_url="http://127.0.0.1:8080", model_name="m", http_client=_AlternatingClient()
    )
    payload = {
        "job_id": "j1",
        "standard_revision_id": "r1",
        "image": "x",
        "detection_points": [{"point_code": "cp1"}, {"point_code": "cp2"}],
    }
    resp = adapter.run_inference(payload)
    by_code = {r.point_code: r for r in resp.per_point_results}
    assert by_code["cp1"].result == "pass"
    assert by_code["cp2"].result == "uncertain"
