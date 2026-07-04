"""Integration: the 10 hot-plug cycles from §20.2, driven through the real HTTP
API and the real mock EdgeCVAgent (no hardware, no network).

Each cycle exercises a hot-plug scenario end-to-end: registration, pull-based
job acquisition, result upload, disconnect/reconnect, lease expiry, fallback,
idempotency and failure handling.
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from src.db.models import _utcnow
from src.db.edge_cv_models import CVJob, CVResult, EdgeCVDevice
from src.qc_model.edge_cv import constants as C
from src.qc_model.edge_cv import service as device_service

from edge_cv_agent.app.config import AgentConfig
from edge_cv_agent.app.main import EdgeCVAgent

from tests.edge_cv_helpers import db_session, client, seeded_db  # noqa: F401


def _agent(client, mock=True, name="jetson-nano-2gb-lab-001"):
    cfg = AgentConfig(device_name=name, device_type="jetson_nano_2gb", service_url="", mock_mode=mock)
    return EdgeCVAgent(client, cfg)


def _create_job(client, image="storage://input/img.jpg", scenario=None):
    payload = {"image_uri": image}
    if scenario:
        payload["mock_scenario"] = scenario
    resp = client.post("/api/cv/jobs", json={"task_type": "defect_candidate_detection", "input_payload": payload})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _drop_mock_runner(db):
    db.query(EdgeCVDevice).filter_by(device_name="mock-edge-cv-runner").delete()
    db.commit()


# ── Cycle 1: no Jetson at startup → CPU fallback ─────────────────────────────
def test_cycle1_no_jetson_cpu_fallback(client, seeded_db):
    _drop_mock_runner(seeded_db)
    job = _create_job(client)
    assert job["status"] == C.JOB_COMPLETED
    assert len(job["result_ids"]) == 1


# ── Cycle 2: mock Jetson registers after startup → processes job ─────────────
def test_cycle2_hotplug_register_and_process(client, seeded_db):
    _drop_mock_runner(seeded_db)
    agent = _agent(client)
    agent.register()
    agent.heartbeat_once()
    job = _create_job(client)
    assert job["status"] == C.JOB_QUEUED  # left for the device to pull
    outcome = agent.poll_once()
    assert outcome["outcome"] == "uploaded"
    final = client.get(f"/api/cv/jobs/{job['cv_job_id']}").json()
    assert final["status"] == C.JOB_COMPLETED
    assert seeded_db.query(CVResult).filter_by(cv_job_id=job["cv_job_id"]).count() == 1


# ── Cycle 3: Jetson disconnects while idle → offline after TTL, fallback ─────
def test_cycle3_idle_disconnect_then_fallback(client, seeded_db):
    _drop_mock_runner(seeded_db)
    agent = _agent(client)
    agent.register()
    # Simulate missed heartbeats.
    dev = seeded_db.query(EdgeCVDevice).filter_by(id=agent.device_id).first()
    dev.last_heartbeat_at = _utcnow() - timedelta(seconds=999)
    seeded_db.commit()
    device_service.sweep_offline_devices(seeded_db, ttl_seconds=35)
    seeded_db.refresh(dev)
    assert dev.status == C.DEVICE_OFFLINE
    # New job must not wait forever → CPU fallback.
    job = _create_job(client)
    assert job["status"] == C.JOB_COMPLETED


# ── Cycle 4: Jetson disconnects during a running job → lease expiry recovery ─
def test_cycle4_disconnect_during_job_lease_expiry(client, seeded_db):
    _drop_mock_runner(seeded_db)
    agent = _agent(client)
    agent.register()
    job = _create_job(client)
    # Agent leases + starts but never uploads (device vanished).
    from edge_cv_agent.app import job_client
    pulled = job_client.pull_next(client, "", agent.auth_token, agent.device_id, agent.session_id, agent.cfg.capabilities())
    job_client.mark_started(client, "", agent.auth_token, pulled["cv_job_id"], agent.device_id, agent.session_id)
    # Force the lease to expire, then run recovery.
    row = seeded_db.query(CVJob).filter_by(id=job["cv_job_id"]).first()
    row.lease_expires_at = _utcnow() - timedelta(seconds=1)
    seeded_db.commit()
    # Device also went offline.
    device_service.sweep_offline_devices(seeded_db, ttl_seconds=0)
    from src.qc_model.edge_cv import dispatcher
    dispatcher.expire_leases(seeded_db)
    row = seeded_db.query(CVJob).filter_by(id=job["cv_job_id"]).first()
    assert row.retry_count == 1
    # No device online → recovered via CPU fallback (completed) — never stuck.
    assert row.status in (C.JOB_COMPLETED, C.JOB_QUEUED, C.JOB_MANUAL_REVIEW)
    assert row.status != C.JOB_RUNNING


# ── Cycle 5: reconnect with new session; stale session cannot upload ─────────
def test_cycle5_reconnect_new_session_stale_rejected(client, seeded_db):
    _drop_mock_runner(seeded_db)
    agent = _agent(client)
    agent.register()
    job = _create_job(client)
    from edge_cv_agent.app import job_client, result_uploader
    from edge_cv_agent.app.cv_pipeline import run_mock_pipeline
    pulled = job_client.pull_next(client, "", agent.auth_token, agent.device_id, agent.session_id, agent.cfg.capabilities())
    old_token, old_session = agent.auth_token, agent.session_id
    # Device reboots → re-register (new session).
    agent.register()
    assert agent.session_id != old_session
    # Old session tries to upload → rejected (409).
    out = run_mock_pipeline(pulled)
    payload = result_uploader.build_result_payload(agent.device_id, old_session, out)
    resp = result_uploader.upload_result(client, "", old_token, pulled["cv_job_id"], payload)
    assert resp.status_code == 409
    # New session can process a fresh job.
    job2 = _create_job(client, image="storage://input/img2.jpg")
    assert agent.poll_once()["outcome"] == "uploaded"
    assert client.get(f"/api/cv/jobs/{job2['cv_job_id']}").json()["status"] == C.JOB_COMPLETED


# ── Cycle 6: device busy at capacity → second job uses CPU fallback ──────────
def test_cycle6_busy_second_job_fallback(client, seeded_db):
    _drop_mock_runner(seeded_db)
    agent = _agent(client)
    agent.register()
    _create_job(client, image="a.jpg")
    from edge_cv_agent.app import job_client
    job_client.pull_next(client, "", agent.auth_token, agent.device_id, agent.session_id, agent.cfg.capabilities())
    dev = seeded_db.query(EdgeCVDevice).filter_by(id=agent.device_id).first()
    assert dev.status == C.DEVICE_BUSY
    # Second job: device at capacity → CPU fallback completes it.
    job2 = _create_job(client, image="b.jpg")
    assert job2["status"] == C.JOB_COMPLETED


# ── Cycle 7: model hash mismatch → job fails safely ─────────────────────────
def test_cycle7_model_hash_mismatch(client, seeded_db):
    _drop_mock_runner(seeded_db)
    agent = _agent(client)
    agent.register()
    job = _create_job(client, scenario="success")
    # Pull, start, then upload with a wrong model hash → service rejects.
    from edge_cv_agent.app import job_client, result_uploader
    from edge_cv_agent.app.cv_pipeline import run_mock_pipeline
    pulled = job_client.pull_next(client, "", agent.auth_token, agent.device_id, agent.session_id, agent.cfg.capabilities())
    job_client.mark_started(client, "", agent.auth_token, pulled["cv_job_id"], agent.device_id, agent.session_id)
    out = run_mock_pipeline(pulled)
    payload = result_uploader.build_result_payload(agent.device_id, agent.session_id, out, model_id=pulled["model"]["model_id"], model_hash="WRONG-HASH")
    resp = result_uploader.upload_result(client, "", agent.auth_token, pulled["cv_job_id"], payload)
    assert resp.status_code == 422
    row = seeded_db.query(CVJob).filter_by(id=job["cv_job_id"]).first()
    assert row.status == C.JOB_MANUAL_REVIEW
    assert row.error_code == "model_hash_mismatch"


# ── Cycle 8: partial/invalid result → validated + manual review ─────────────
def test_cycle8_partial_result_manual_review(client, seeded_db):
    _drop_mock_runner(seeded_db)
    agent = _agent(client)
    agent.register()
    job = _create_job(client, scenario="partial_result")
    outcome = agent.poll_once()  # agent uploads partial → service 422
    # Job escalated to manual review (never silently completed).
    row = seeded_db.query(CVJob).filter_by(id=job["cv_job_id"]).first()
    assert row.status == C.JOB_MANUAL_REVIEW


# ── Cycle 9: duplicate result upload → idempotent ───────────────────────────
def test_cycle9_duplicate_result_idempotent(client, seeded_db):
    _drop_mock_runner(seeded_db)
    agent = _agent(client)
    agent.register()
    job = _create_job(client)
    from edge_cv_agent.app import job_client, result_uploader
    from edge_cv_agent.app.cv_pipeline import run_mock_pipeline
    pulled = job_client.pull_next(client, "", agent.auth_token, agent.device_id, agent.session_id, agent.cfg.capabilities())
    job_client.mark_started(client, "", agent.auth_token, pulled["cv_job_id"], agent.device_id, agent.session_id)
    out = run_mock_pipeline(pulled)
    payload = result_uploader.build_result_payload(agent.device_id, agent.session_id, out)
    r1 = result_uploader.upload_result(client, "", agent.auth_token, pulled["cv_job_id"], payload)
    r2 = result_uploader.upload_result(client, "", agent.auth_token, pulled["cv_job_id"], payload)
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.json()["result_id"] == r2.json()["result_id"]
    assert seeded_db.query(CVResult).filter_by(cv_job_id=job["cv_job_id"]).count() == 1


# ── Cycle 10: many images, mixed outcomes, no service crash ─────────────────
def test_cycle10_many_images_no_crash(client, seeded_db):
    _drop_mock_runner(seeded_db)
    agent = _agent(client)
    agent.register()
    scenarios = ["success", "success", "timeout", "partial_result", "success"]
    job_ids = [_create_job(client, image=f"img{i}.jpg", scenario=sc)["cv_job_id"] for i, sc in enumerate(scenarios)]
    # Drain the queue: process every pullable job (failures self-recover).
    for _ in range(20):
        if agent.poll_once() is None:
            break
    # Expire any lingering lease and recover, so nothing stays leased/running.
    for row in seeded_db.query(CVJob).all():
        if row.lease_expires_at is not None:
            row.lease_expires_at = _utcnow() - timedelta(seconds=1)
    seeded_db.commit()
    from src.qc_model.edge_cv import dispatcher
    dispatcher.expire_leases(seeded_db)
    for _ in range(20):
        if agent.poll_once() is None:
            break
    terminal = {C.JOB_COMPLETED, C.JOB_FAILED, C.JOB_MANUAL_REVIEW, C.JOB_CANCELLED}
    statuses = [seeded_db.query(CVJob).filter_by(id=j).first().status for j in job_ids]
    assert all(s in terminal for s in statuses), statuses
    # Health check still serves — service did not crash.
    assert client.get("/health").json()["status"] == "ok"
