"""Jetson runner HTTP API (provision, bind, health, readiness, validate)."""
from __future__ import annotations

from tests.jetson_helpers import db_session, client, make_workstation  # noqa: F401


def test_provision_and_read(client):
    r = client.post("/api/qc/jetson/runners", json={"jetson_device_id": "jetson-1", "pubkey_fingerprint": "1111-2222"})
    assert r.status_code == 201, r.text
    assert r.json()["pairing_status"] == "unpaired"
    got = client.get("/api/qc/jetson/runners/jetson-1")
    assert got.status_code == 200
    assert got.json()["jetson_device_id"] == "jetson-1"


def test_binding_and_health_and_list(client, db_session):
    make_workstation(db_session, "WS-1")
    client.post("/api/qc/jetson/runners", json={"jetson_device_id": "jetson-1", "pubkey_fingerprint": "fp"})
    b = client.post("/api/qc/jetson/bindings", json={
        "jetson_device_id": "jetson-1", "pubkey_fingerprint": "fp",
        "workstation_id": "WS-1", "pad_device_id": "pad-1", "pairing_path": "usb",
    })
    assert b.status_code == 201, b.text
    assert b.json()["pairing_status"] == "paired"
    assert b.json()["workstation_id"] == "WS-1"

    h = client.post("/api/qc/jetson/runners/jetson-1/health", json={
        "jetson_device_id": "jetson-1", "service_up": True, "model_loaded": True,
        "temperature_c": 60.0, "readiness_state": "jetson_ready", "last_inference_latency_ms": 320,
    })
    assert h.status_code == 200
    assert h.json()["health"]["readiness_state"] == "jetson_ready"
    assert h.json()["health"]["last_inference_latency_ms"] == 320

    lst = client.get("/api/qc/jetson/runners")
    assert len(lst.json()) == 1


def test_binding_unknown_workstation_404(client):
    client.post("/api/qc/jetson/runners", json={"jetson_device_id": "jetson-1", "pubkey_fingerprint": "fp"})
    b = client.post("/api/qc/jetson/bindings", json={
        "jetson_device_id": "jetson-1", "pubkey_fingerprint": "fp",
        "workstation_id": "GONE", "pad_device_id": "pad-1", "pairing_path": "usb",
    })
    assert b.status_code == 404


def test_readiness_endpoint_fail_closed(client):
    r = client.post("/api/qc/jetson/readiness", json={
        "sku_selected": True, "standard_installed": True, "jetson_reachable": False,
    })
    body = r.json()
    assert body["readiness_state"] == "jetson_unreachable"
    assert body["can_submit_inspection"] is False


def test_inference_request_validation_endpoint(client):
    ok = client.post("/api/qc/jetson/inference/validate", json={
        "job_id": "j", "standard_revision_id": "r", "image": "x",
        "detection_points": [{"point_code": "cp1"}],
    })
    assert ok.status_code == 200 and ok.json()["valid"] is True
    bad = client.post("/api/qc/jetson/inference/validate", json={
        "job_id": "j", "standard_revision_id": "r", "image": "x", "detection_points": [],
    })
    assert bad.status_code == 422
