"""Tests for Stage 3 Group B's remote chat-completions VLM provider (GAP-06).

Mirrors the ServerVLMInspectionProvider test pattern in
tests/test_qc_real_vlm_provider.py: subclass and stub ``_call_backend`` so
tests never touch a live network endpoint.
"""
from __future__ import annotations

import json

import pytest

from src.qc_model.production.provider import (
    DetectionInspectionRequest,
    ProductionProviderError,
    ProductionProviderNotConfigured,
    ProductionProviderSchemaError,
    get_production_inspection_provider,
    production_provider_status,
)
from src.qc_model.production.remote_chat_provider import RemoteChatVlmInspectionProvider


def _good_chat_response(dp="dp", disposition="pass_recommended"):
    body = {
        "detection_point_code": dp,
        "disposition": disposition,
        "observed_features": ["f1"],
        "defect_features": [],
        "normal_features_matched": ["f1"],
        "evidence_regions": [{"bbox": [1, 2, 3, 4]}],
        "confidence": 0.87,
        "uncertainty": "",
        "review_required_conditions": [],
        "provider": "remote_chat_vlm",
        "model": "qwen3-vl-4b-int4",
    }
    return {"choices": [{"message": {"content": json.dumps(body)}}]}


class _StubbedRemoteProvider(RemoteChatVlmInspectionProvider):
    def __init__(self, backend_response, **kwargs):
        kwargs.setdefault("base_url", "http://127.0.0.1:18443")
        kwargs.setdefault("model", "qwen3-vl-4b-int4")
        super().__init__(**kwargs)
        self._backend_response = backend_response
        self.captured_payload = None

    def _call_backend(self, payload):
        self.captured_payload = payload
        if isinstance(self._backend_response, Exception):
            raise self._backend_response
        return self._backend_response


def _request(image_ref="data:image/png;base64,QUJD", **kw):
    kw.setdefault("detection_point_code", "dp")
    kw.setdefault("checkpoint_category", "visual_defect")
    kw.setdefault("confirmed_content", {"normal_visual_features": ["f1"]})
    return DetectionInspectionRequest(image_references=[image_ref], **kw)


# ── Configuration / fail-closed on missing config ────────────────────────────


def test_unconfigured_provider_fails_closed():
    provider = RemoteChatVlmInspectionProvider(base_url="", model="")
    with pytest.raises(ProductionProviderNotConfigured):
        provider.inspect(_request())


def test_missing_model_name_is_not_configured():
    provider = RemoteChatVlmInspectionProvider(base_url="http://127.0.0.1:18443", model="")
    assert provider.is_configured is False


def test_missing_image_reference_fails_closed():
    provider = _StubbedRemoteProvider(_good_chat_response())
    req = DetectionInspectionRequest("dp", "visual_defect", {}, [])
    with pytest.raises(ProductionProviderError):
        provider.inspect(req)


# ── Image resolution: local path only, no SSRF-prone URL fetch ──────────────


def test_http_image_reference_is_refused(tmp_path):
    provider = _StubbedRemoteProvider(_good_chat_response())
    req = _request(image_ref="http://internal-host/img.jpg")
    with pytest.raises(ProductionProviderError, match="http_image_reference_not_supported"):
        provider.inspect(req)


def test_missing_local_image_file_fails_closed():
    provider = _StubbedRemoteProvider(_good_chat_response())
    req = _request(image_ref="/tmp/definitely-does-not-exist-12345.jpg")
    with pytest.raises(ProductionProviderError, match="image_not_found"):
        provider.inspect(req)


def test_oversized_local_image_is_refused(tmp_path):
    big = tmp_path / "big.jpg"
    big.write_bytes(b"\x00" * 200)
    provider = _StubbedRemoteProvider(_good_chat_response(), max_image_bytes=100)
    req = _request(image_ref=str(big))
    with pytest.raises(ProductionProviderError, match="image_too_large"):
        provider.inspect(req)


def test_data_url_reference_is_embedded_directly(tmp_path):
    provider = _StubbedRemoteProvider(_good_chat_response())
    data_url = "data:image/png;base64,QUJD"
    req = _request(image_ref=data_url)
    result = provider.inspect(req)
    assert result.disposition == "pass_recommended"
    image_part = provider.captured_payload["messages"][0]["content"][1]
    assert image_part["image_url"]["url"] == data_url


# ── Real local image → payload shape ─────────────────────────────────────────


def test_local_image_is_embedded_as_data_url(tmp_path):
    image = tmp_path / "capture.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    provider = _StubbedRemoteProvider(_good_chat_response())
    result = provider.inspect(_request(image_ref=str(image)))

    assert result.disposition == "pass_recommended"
    assert result.provider == "remote_chat_vlm"
    payload = provider.captured_payload
    assert payload["model"] == "qwen3-vl-4b-int4"
    content = payload["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert "detection_point_code" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


# ── Fail-closed on malformed / missing response shape ────────────────────────


def test_missing_choices_fails_closed():
    provider = _StubbedRemoteProvider({"unexpected": "shape"})
    with pytest.raises(ProductionProviderSchemaError, match="missing choices"):
        provider.inspect(_request())


def test_empty_content_fails_closed():
    provider = _StubbedRemoteProvider({"choices": [{"message": {"content": "   "}}]})
    with pytest.raises(ProductionProviderSchemaError, match="content is empty"):
        provider.inspect(_request())


def test_non_json_content_fails_closed():
    provider = _StubbedRemoteProvider({"choices": [{"message": {"content": "I cannot help."}}]})
    with pytest.raises(ProductionProviderSchemaError, match="not JSON"):
        provider.inspect(_request())


def test_markdown_fenced_json_is_accepted():
    body = _good_chat_response()
    fenced = "```json\n" + body["choices"][0]["message"]["content"] + "\n```"
    body["choices"][0]["message"]["content"] = fenced
    provider = _StubbedRemoteProvider(body)
    result = provider.inspect(_request())
    assert result.disposition == "pass_recommended"


def test_schema_invalid_parsed_json_fails_closed():
    bad = {"choices": [{"message": {"content": json.dumps({"disposition": "approve"})}}]}
    provider = _StubbedRemoteProvider(bad)
    with pytest.raises(ProductionProviderSchemaError, match="malformed output"):
        provider.inspect(_request())


def test_transport_error_fails_closed():
    provider = _StubbedRemoteProvider(ConnectionRefusedError("tunnel down"))
    with pytest.raises(ProductionProviderError, match="backend error"):
        provider.inspect(_request())


# ── Provider selection wiring (GAP-05) ───────────────────────────────────────


def test_remote_chat_vlm_is_selectable_by_name(monkeypatch):
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "remote_chat_vlm")
    monkeypatch.delenv("VLM_BASE_URL", raising=False)
    provider = get_production_inspection_provider()
    assert isinstance(provider, RemoteChatVlmInspectionProvider)
    assert provider.is_configured is False  # no VLM_BASE_URL set


def test_stage3_group_b_alias_is_selectable(monkeypatch):
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "stage3_group_b")
    provider = get_production_inspection_provider()
    assert isinstance(provider, RemoteChatVlmInspectionProvider)


def test_status_reports_remote_chat_vlm_selection(monkeypatch):
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "remote_chat_vlm")
    monkeypatch.setenv("VLM_BASE_URL", "http://127.0.0.1:18443")
    monkeypatch.setenv("VLM_MODEL", "qwen3-vl-4b-int4")
    status = production_provider_status()
    assert status["selected"] == "remote_chat_vlm"
    assert status["provider_name"] == "remote_chat_vlm"
    assert status["configured"] is True
    assert status["production_eligible"] is True
