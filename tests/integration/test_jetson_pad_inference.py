"""Integration: full Pad↔Jetson pairing + inference + Server binding sync.

Exercises one production-line slice end to end, headless (no display, no hardware):

  CV producer (Nano capture / Pad framing) → captured frame
        → Pad pairs with the Xavier-NX Jetson (USB or Wi-Fi, headless)
        → Pad sends a signed qc-model inference request over LAN
        → Jetson returns per-point evidence (not a verdict)
        → Pad reports the pairing binding + health to the Server on sync
        → re-pair to a new Pad is fail-closed (old Pad rejected, no grace)
"""
from __future__ import annotations

from jetson_runner.app.config import RunnerConfig
from jetson_runner.app.identity import generate_identity
from jetson_runner.app.main import InferenceRejected, JetsonRunnerService
from jetson_runner.app.pad_client import MockPad
from src.qc_model.jetson import constants as C

from tests.jetson_helpers import db_session, client, make_workstation  # noqa: F401


def _inference_request(job="job-1"):
    return {
        "job_id": job,
        "standard_revision_id": "rev-1",
        "bundle_version": "1.0.0",
        "image": "frame://captured-by-cv-frontend",
        "detection_points": [
            {"point_code": "flower_core_centered", "label": "core centered", "mock_result": "pass"},
            {"point_code": "pearl_count", "label": "pearl count", "mock_result": "uncertain"},
        ],
    }


def test_full_pairing_inference_and_server_sync(client, db_session):
    make_workstation(db_session, "WS-LINE-1")

    # 1) Provision the Jetson off-floor (headless bench step).
    jetson = JetsonRunnerService(RunnerConfig(mock_mode=True), identity=generate_identity("jetson-xnx-1"))
    client.post("/api/qc/jetson/runners", json={
        "jetson_device_id": jetson.identity.jetson_device_id,
        "pubkey_fingerprint": jetson.identity.fingerprint,
    })

    # 2) On the floor: Pad pairs over USB (physical proof) — no Server needed.
    pad = MockPad("pad-line-1")
    pad.pair_over_usb(jetson.pairing)

    # 3) Pad sends a signed inference request over LAN; Jetson returns evidence.
    resp = pad.call(jetson, _inference_request())
    assert resp["job_id"] == "job-1"
    results = {r["point_code"]: r["result"] for r in resp["per_point_results"]}
    assert results == {"flower_core_centered": "pass", "pearl_count": "uncertain"}

    # 4) Pad syncs the pairing binding to the Server (offline-tolerant).
    b = client.post("/api/qc/jetson/bindings", json=pad.binding_sync_payload("WS-LINE-1", jetson.identity.fingerprint))
    assert b.status_code == 201, b.text
    assert b.json()["pairing_status"] == "paired"
    assert b.json()["paired_pad_device_id"] == "pad-line-1"

    # 5) Pad relays Jetson health so it shows on the Pad/admin (headless visibility).
    report = jetson.health_report()
    h = client.post(f"/api/qc/jetson/runners/{jetson.identity.jetson_device_id}/health", json={
        "jetson_device_id": jetson.identity.jetson_device_id,
        "service_up": report["service_up"], "model_loaded": report["model_loaded"],
        "temperature_c": report["temperature_c"], "readiness_state": report["readiness_state"],
    })
    assert h.json()["health"]["readiness_state"] == C.READY

    # 6) Re-pair to a NEW Pad → old Pad is rejected with no grace, Server updates.
    new_pad = MockPad("pad-line-1-replacement")
    new_pad.pair_over_usb(jetson.pairing)
    try:
        pad.call(jetson, _inference_request("job-2"))
        assert False, "old Pad should be rejected after re-pair"
    except InferenceRejected as exc:
        assert exc.reason == "unpaired_caller"
    assert new_pad.call(jetson, _inference_request("job-3"))["job_id"] == "job-3"

    b2 = client.post("/api/qc/jetson/bindings", json=new_pad.binding_sync_payload("WS-LINE-1", jetson.identity.fingerprint))
    assert b2.json()["paired_pad_device_id"] == "pad-line-1-replacement"


def test_inspection_blocked_when_jetson_unreachable(client):
    # Fail-closed: no Jetson reachable → operator cannot submit.
    r = client.post("/api/qc/jetson/readiness", json={
        "sku_selected": True, "standard_installed": True, "jetson_reachable": False,
    })
    assert r.json()["can_submit_inspection"] is False
