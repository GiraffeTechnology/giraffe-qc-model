"""Live-capture upload → qc-model handoff (Live-Capture Auto-Lock addendum)."""
from __future__ import annotations

from src.db.edge_cv_models import CVCapturedPhoto, CVJob
from src.qc_model.edge_cv.captures import capture_time_label
from datetime import datetime, timezone

from tests.edge_cv_helpers import db_session, client, register_device, auth  # noqa: F401


def test_capture_time_label_format():
    dt = datetime(2026, 7, 4, 14, 32, 10, tzinfo=timezone.utc)
    assert capture_time_label(dt) == "0704_143210"


def test_capture_upload_persists_and_dispatches_job(client, db_session):
    reg = register_device(client, caps=["opencv", "defect_candidate_detection", "live_candidate_lock_capture"])
    resp = client.post(
        "/api/edge-cv/captures/upload",
        json={
            "device_id": reg["device_id"],
            "session_id": reg["session_id"],
            "user_id": "operator_123",
            "captured_at": "2026-07-04T14:32:10+08:00",
            "candidate_confidence": 0.87,
            "gps": {"lat": 22.3193, "lon": 114.1694, "accuracy_m": 8.5},
            "image_uri": "storage://captures/frame001.jpg",
        },
        headers=auth(reg["auth_token"]),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["qc_model_dispatch_status"] == "dispatched"
    assert body["cv_job_id"] is not None
    assert body["capture_time_label"] == "0704_143210"

    cap = db_session.query(CVCapturedPhoto).filter_by(id=body["capture_id"]).first()
    assert cap.captured_by_user_id == "operator_123"
    assert cap.gps_lat == 22.3193
    assert cap.linked_cv_job_id == body["cv_job_id"]

    job = db_session.query(CVJob).filter_by(id=body["cv_job_id"]).first()
    assert job.source_asset_id == "storage://captures/frame001.jpg"
    assert job.requested_by == "operator_123"


def test_capture_upload_rejects_stale_session(client):
    reg = register_device(client, caps=["live_candidate_lock_capture", "defect_candidate_detection"])
    # New registration supersedes the first session.
    register_device(client, caps=["live_candidate_lock_capture", "defect_candidate_detection"])
    resp = client.post(
        "/api/edge-cv/captures/upload",
        json={
            "device_id": reg["device_id"],
            "session_id": reg["session_id"],
            "user_id": "op",
            "image_uri": "storage://x.jpg",
        },
        headers=auth(reg["auth_token"]),
    )
    assert resp.status_code == 409


def test_capture_upload_requires_device_token(client):
    reg = register_device(client)
    resp = client.post(
        "/api/edge-cv/captures/upload",
        json={"device_id": reg["device_id"], "session_id": reg["session_id"], "image_uri": "x.jpg"},
    )
    assert resp.status_code == 401
