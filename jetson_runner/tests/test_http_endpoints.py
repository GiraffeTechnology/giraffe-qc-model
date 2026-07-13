"""HTTP-layer tests for the Jetson runner's FastAPI app (build_app).

main() itself is pragma: no-cover (it starts a real uvicorn server), but the
routing/status-code logic it wires up is real product code that WS4's Pad
client depends on -- exercise it with TestClient instead of only unit-testing
the underlying service methods.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from jetson_runner.app.adapters.base import InferenceAdapter
from jetson_runner.app.config import RunnerConfig
from jetson_runner.app.identity import generate_identity
from jetson_runner.app.main import JetsonRunnerService, build_app
from src.qc_model.jetson.contract import InferenceResponse, PerPointResult


def _client(**kwargs) -> TestClient:
    cfg = RunnerConfig(mock_mode=True, **kwargs)
    svc = JetsonRunnerService(cfg, identity=generate_identity("jetson-test"))
    return TestClient(build_app(cfg, svc))


def test_health_endpoint():
    client = _client()
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["readiness_state"] == "jetson_ready"
    assert body["mock"] is True
    assert body["jetson_device_id"] == "jetson-test"


def test_pair_usb_then_infer_ok():
    client = _client()
    pair = client.post("/pair/usb", json={"pad_device_id": "pad-1", "pad_pubkey": "pub-1"})
    assert pair.status_code == 200
    pair_key = pair.json()["pair_key"]

    import hmac
    import hashlib
    import json as jsonlib

    request = {
        "job_id": "j1",
        "standard_revision_id": "r1",
        "image": "frame://x",
        "detection_points": [{"point_code": "cp1", "mock_result": "pass"}],
    }
    canonical = jsonlib.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(pair_key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()

    resp = client.post(
        "/infer", json={"pad_device_id": "pad-1", "signature": signature, "request": request}
    )
    assert resp.status_code == 200
    assert resp.json()["per_point_results"][0]["result"] == "pass"


def test_pair_usb_missing_fields_422():
    client = _client()
    resp = client.post("/pair/usb", json={"pad_device_id": "pad-1"})
    assert resp.status_code == 422


def test_pair_wifi_without_open_window_403():
    client = _client()
    resp = client.post(
        "/pair/wifi",
        json={"pad_device_id": "pad-1", "pad_pubkey": "pub-1", "confirmed_fingerprint": "0000-0000-0000-0000"},
    )
    assert resp.status_code == 403
    assert "pairing_window_closed" in resp.json()["detail"]


def test_pair_wifi_wrong_fingerprint_403():
    cfg = RunnerConfig(mock_mode=True)
    svc = JetsonRunnerService(cfg, identity=generate_identity("jetson-test"))
    svc.pairing.open_pairing_window(seconds=120)
    client = TestClient(build_app(cfg, svc))
    resp = client.post(
        "/pair/wifi",
        json={"pad_device_id": "pad-1", "pad_pubkey": "pub-1", "confirmed_fingerprint": "0000-0000-0000-0000"},
    )
    assert resp.status_code == 403
    assert "fingerprint_mismatch" in resp.json()["detail"]


def test_pair_wifi_correct_fingerprint_ok():
    cfg = RunnerConfig(mock_mode=True)
    svc = JetsonRunnerService(cfg, identity=generate_identity("jetson-test"))
    svc.pairing.open_pairing_window(seconds=120)
    client = TestClient(build_app(cfg, svc))
    resp = client.post(
        "/pair/wifi",
        json={
            "pad_device_id": "pad-1",
            "pad_pubkey": "pub-1",
            "confirmed_fingerprint": svc.identity.fingerprint,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["pairing_path"] == "wifi"


def test_infer_unpaired_caller_403():
    client = _client()
    resp = client.post(
        "/infer",
        json={
            "pad_device_id": "pad-unknown",
            "signature": "deadbeef",
            "request": {"job_id": "j1", "standard_revision_id": "r1", "image": "x", "detection_points": [{"point_code": "cp1"}]},
        },
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "unpaired_caller"


def test_infer_runtime_not_ready_503():
    class _NotReady(InferenceAdapter):
        @property
        def adapter_name(self) -> str:
            return "fake"

        @property
        def model_name(self) -> str:
            return "fake-model"

        def is_ready(self) -> bool:
            return False

        def run_inference(self, payload: dict) -> InferenceResponse:
            raise AssertionError("must not be called")

    cfg = RunnerConfig(mock_mode=False)
    svc = JetsonRunnerService(cfg, identity=generate_identity("jetson-test"), adapter=_NotReady())
    client = TestClient(build_app(cfg, svc))
    pair = client.post("/pair/usb", json={"pad_device_id": "pad-1", "pad_pubkey": "pub-1"})
    pair_key = pair.json()["pair_key"]

    import hmac
    import hashlib
    import json as jsonlib

    request = {"job_id": "j1", "standard_revision_id": "r1", "image": "x", "detection_points": [{"point_code": "cp1"}]}
    canonical = jsonlib.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(pair_key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()

    resp = client.post("/infer", json={"pad_device_id": "pad-1", "signature": signature, "request": request})
    assert resp.status_code == 503
    assert resp.json()["detail"] == "runtime_not_ready"


def test_phase1_loopback_disabled_by_default_404():
    client = _client()
    resp = client.post("/phase1/pair-loopback", json={"pad_device_id": "pad-1", "pad_pubkey": "pub-1"})
    assert resp.status_code == 404
