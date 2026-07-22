"""Tests for the Stage 3 Group B real-device harness
(scripts/jetson_stage3_run_group_b.py).

Network calls go through RemoteChatVlmInspectionProvider, whose own
_call_backend is monkeypatched — no real network or hardware is touched.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(rel_path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


harness = _load("scripts/jetson_stage3_run_group_b.py", "group_b_harness")
gate = _load("scripts/ci/stage3_authorization_gate.py", "stage3_gate_b")

from src.qc_model.production.remote_chat_provider import RemoteChatVlmInspectionProvider  # noqa: E402


def _good_response(disposition="pass_recommended"):
    body = {
        "detection_point_code": "dp1", "disposition": disposition,
        "observed_features": ["f1"], "defect_features": [],
        "normal_features_matched": ["f1"], "evidence_regions": [],
        "confidence": 0.9, "uncertainty": "", "review_required_conditions": [],
        "provider": "remote_chat_vlm", "model": "qwen3-vl-4b-int4",
    }
    return {"choices": [{"message": {"content": json.dumps(body)}}]}


class _StubProvider(RemoteChatVlmInspectionProvider):
    def __init__(self, response_or_exc):
        super().__init__(base_url="http://127.0.0.1:18443", model="qwen3-vl-4b-int4")
        self._response_or_exc = response_or_exc

    def _call_backend(self, payload):
        if isinstance(self._response_or_exc, Exception):
            raise self._response_or_exc
        return self._response_or_exc


def test_run_case_records_success(tmp_path):
    image = tmp_path / "front.jpg"
    image.write_bytes(b"jpeg-bytes")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    provider = _StubProvider(_good_response())

    row, ok = harness.run_case(
        provider,
        {"case_id": "c1", "image_path": str(image), "detection_point_code": "dp1"},
        evidence_dir,
    )
    assert ok is True
    assert row["verdict"] == "pass"
    assert Path(row["request_ref"]).exists()
    assert Path(row["response_ref"]).exists()


def test_run_case_records_fail_verdict(tmp_path):
    image = tmp_path / "front.jpg"
    image.write_bytes(b"jpeg-bytes")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    provider = _StubProvider(_good_response(disposition="reject_recommended"))

    row, ok = harness.run_case(
        provider,
        {"case_id": "c1", "image_path": str(image), "detection_point_code": "dp1"},
        evidence_dir,
    )
    assert ok is True  # the call succeeded; the *verdict* is reject
    assert row["verdict"] == "reject"


def test_run_case_transport_failure_does_not_fabricate_pass(tmp_path):
    image = tmp_path / "front.jpg"
    image.write_bytes(b"jpeg-bytes")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    provider = _StubProvider(ConnectionRefusedError("tunnel down"))

    row, ok = harness.run_case(
        provider,
        {"case_id": "c1", "image_path": str(image), "detection_point_code": "dp1"},
        evidence_dir,
    )
    assert ok is False
    assert row["passed"] is False
    assert row["verdict"] == "reject"
    assert "ConnectionRefusedError" in row["anomaly_notes"][0]


def test_main_refuses_when_gate_closed(tmp_path, monkeypatch):
    output = tmp_path / "report.json"

    class _ClosedGate:
        open = False
        def summary(self):
            return "CLOSED — test"

    monkeypatch.setattr(harness, "_load_gate", lambda: type("G", (), {"evaluate": staticmethod(lambda: _ClosedGate())}))
    monkeypatch.setattr(
        "sys.argv",
        [
            "jetson_stage3_run_group_b.py",
            "--vlm-base-url", "http://127.0.0.1:18443", "--vlm-model", "qwen3-vl-4b-int4",
            "--cases", str(tmp_path / "cases.json"), "--model-backend", "cpu",
            "--output", str(output),
        ],
    )
    exit_code = harness.main()
    assert exit_code == 1
    assert not output.exists()


def test_main_forces_blocked_status_without_remote_manifest_sha(tmp_path, monkeypatch):
    image = tmp_path / "front.jpg"
    image.write_bytes(b"jpeg-bytes")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([
        {"case_id": "c1", "image_path": str(image), "detection_point_code": "dp1"}
    ]))
    output = tmp_path / "report.json"

    class _OpenGate:
        open = True
        def summary(self):
            return "OPEN — test"

    monkeypatch.setattr(harness, "_load_gate", lambda: type("G", (), {"evaluate": staticmethod(lambda: _OpenGate())}))

    def fake_backend(self, payload):
        return _good_response()

    monkeypatch.setattr(RemoteChatVlmInspectionProvider, "_call_backend", fake_backend)

    monkeypatch.setattr(
        "sys.argv",
        [
            "jetson_stage3_run_group_b.py",
            "--vlm-base-url", "http://127.0.0.1:18443", "--vlm-model", "qwen3-vl-4b-int4",
            "--cases", str(cases_path), "--model-backend", "cpu",
            "--output", str(output),
        ],
    )
    exit_code = harness.main()
    assert exit_code == 1  # blocked is never a success exit
    report = json.loads(output.read_text())
    assert report["status"] == "blocked"
    assert report["identity_verified"] is False
    assert report["summary"]["passed_case_count"] == 1  # real evidence still recorded


def test_main_passes_with_remote_manifest_sha(tmp_path, monkeypatch):
    image = tmp_path / "front.jpg"
    image.write_bytes(b"jpeg-bytes")
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(json.dumps([
        {"case_id": "c1", "image_path": str(image), "detection_point_code": "dp1"}
    ]))
    output = tmp_path / "report.json"

    class _OpenGate:
        open = True
        def summary(self):
            return "OPEN — test"

    monkeypatch.setattr(harness, "_load_gate", lambda: type("G", (), {"evaluate": staticmethod(lambda: _OpenGate())}))

    def fake_backend(self, payload):
        return _good_response()

    monkeypatch.setattr(RemoteChatVlmInspectionProvider, "_call_backend", fake_backend)

    monkeypatch.setattr(
        "sys.argv",
        [
            "jetson_stage3_run_group_b.py",
            "--vlm-base-url", "http://127.0.0.1:18443", "--vlm-model", "qwen3-vl-4b-int4",
            "--cases", str(cases_path), "--model-backend", "cpu",
            "--remote-manifest-sha256", "a" * 64,
            "--output", str(output),
        ],
    )
    exit_code = harness.main()
    assert exit_code == 0
    report = json.loads(output.read_text())
    assert report["status"] == "passed"
    assert report["identity_verified"] is True
    assert report["model"]["manifest_sha256"] == "a" * 64
    assert report["stage3_group"] == "B"
    assert report["vlm_execution_location"] == "remote"
