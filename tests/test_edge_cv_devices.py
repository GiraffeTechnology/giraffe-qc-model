"""Unit tests: device registration, sessions, heartbeat, TTL, state, capability
matching, model metadata (§20.1)."""
from __future__ import annotations

from datetime import timedelta

from src.db.models import _utcnow
from src.db.edge_cv_models import EdgeCVDevice, EdgeCVDeviceSession, EdgeCVModel
from src.qc_model.edge_cv import constants as C
from src.qc_model.edge_cv import service
from src.qc_model.edge_cv.dispatcher import _capable_devices, create_job
from src.qc_model.edge_cv.constants import device_transition_allowed

from tests.edge_cv_helpers import db_session, client, seeded_db  # noqa: F401


def test_register_creates_device_and_session_and_token(db_session):
    device, sess, token = service.register_device(
        db_session, device_name="jetson-a", device_type="jetson_nano_2gb",
        capabilities=["defect_candidate_detection"],
    )
    assert device.status == C.DEVICE_ONLINE
    assert sess.status == "active"
    assert token
    from src.qc_model.edge_cv.tokens import verify_device_token
    claims = verify_device_token(token)
    assert claims["device_id"] == device.id and claims["session_id"] == sess.session_id


def test_reregister_keeps_device_id_new_session_closes_old(db_session):
    d1, s1, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb")
    d2, s2, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb")
    assert d1.id == d2.id
    assert s1.session_id != s2.session_id
    old = db_session.query(EdgeCVDeviceSession).filter_by(session_id=s1.session_id).first()
    assert old.status == "ended" and old.disconnect_reason == "superseded_by_new_session"


def test_heartbeat_updates_ttl_and_records_metrics(db_session):
    d, s, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb")
    before = d.last_heartbeat_at
    service.heartbeat(db_session, device_id=d.id, session_id=s.session_id, metrics={"cpu_usage_percent": 10.0, "memory_used_mb": 800, "memory_total_mb": 2048})
    db_session.refresh(d)
    assert d.last_heartbeat_at >= before
    from src.db.edge_cv_models import EdgeCVDeviceMetric
    assert db_session.query(EdgeCVDeviceMetric).filter_by(device_id=d.id).count() == 1


def test_heartbeat_rejects_stale_session(db_session):
    d, s1, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb")
    service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb")  # new session
    import pytest
    with pytest.raises(service.InvalidSession):
        service.heartbeat(db_session, device_id=d.id, session_id=s1.session_id)


def test_heartbeat_derives_degraded_from_high_memory(db_session):
    d, s, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb")
    service.heartbeat(db_session, device_id=d.id, session_id=s.session_id, metrics={"memory_used_mb": 2000, "memory_total_mb": 2048})
    db_session.refresh(d)
    assert d.status == C.DEVICE_DEGRADED


def test_heartbeat_busy_when_at_capacity(db_session):
    d, s, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb", max_concurrent_jobs=1)
    service.heartbeat(db_session, device_id=d.id, session_id=s.session_id, active_job_count=1)
    db_session.refresh(d)
    assert d.status == C.DEVICE_BUSY


def test_ttl_sweep_marks_offline_without_restart(db_session):
    d, s, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb")
    d.last_heartbeat_at = _utcnow() - timedelta(seconds=999)
    db_session.commit()
    transitioned = service.sweep_offline_devices(db_session, ttl_seconds=35)
    assert d.id in {x.id for x in transitioned}
    db_session.refresh(d)
    assert d.status == C.DEVICE_OFFLINE
    old = db_session.query(EdgeCVDeviceSession).filter_by(session_id=s.session_id).first()
    assert old.status == "ended" and old.disconnect_reason == "heartbeat_ttl"


def test_ttl_sweep_leaves_recent_device_online(db_session):
    d, s, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb")
    service.sweep_offline_devices(db_session, ttl_seconds=35)
    db_session.refresh(d)
    assert d.status == C.DEVICE_ONLINE


def test_disable_enable_device(db_session):
    d, s, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb")
    service.disable_device(db_session, d.id)
    db_session.refresh(d)
    assert d.status == C.DEVICE_MAINTENANCE and d.is_enabled is False
    service.enable_device(db_session, d.id)
    db_session.refresh(d)
    assert d.is_enabled is True and d.status == C.DEVICE_OFFLINE


def test_device_state_transitions_table():
    assert device_transition_allowed(C.DEVICE_ONLINE, C.DEVICE_BUSY)
    assert device_transition_allowed(C.DEVICE_BUSY, C.DEVICE_ONLINE)
    assert device_transition_allowed(C.DEVICE_ONLINE, C.DEVICE_OFFLINE)
    assert device_transition_allowed(C.DEVICE_OFFLINE, C.DEVICE_REGISTERING)
    # An online device cannot jump straight back from offline to busy.
    assert not device_transition_allowed(C.DEVICE_OFFLINE, C.DEVICE_BUSY)


def test_capability_matching_filters_incapable_device(seeded_db):
    # A registered device advertising the capability is a candidate; one that
    # does not is filtered out. The seeded (session-less, offline) mock runner
    # is NOT a candidate — it has no live session/heartbeat.
    service.register_device(seeded_db, device_name="strong", device_type="mock_runner", capabilities=["defect_candidate_detection", "opencv"])
    service.register_device(seeded_db, device_name="weak", device_type="mock_runner", capabilities=["image_preprocess"])
    job = create_job(seeded_db, task_type="defect_candidate_detection", auto_dispatch=False)
    matched = _capable_devices(seeded_db, job)
    names = {x.device_name for x in matched}
    assert "strong" in names
    assert "weak" not in names
    assert "mock-edge-cv-runner" not in names  # seeded profile, no live session


def test_seeded_device_without_session_is_not_capable(seeded_db):
    # Regression: a seeded device must never be treated as an available puller.
    job = create_job(seeded_db, task_type="defect_candidate_detection", auto_dispatch=False)
    assert _capable_devices(seeded_db, job) == []


def test_stale_heartbeat_device_not_capable(db_session):
    from datetime import timedelta
    d, s, _ = service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb", capabilities=["defect_candidate_detection"])
    d.last_heartbeat_at = _utcnow() - timedelta(seconds=999)  # gone silent, not yet swept
    db_session.commit()
    job = create_job(db_session, task_type="defect_candidate_detection", auto_dispatch=False)
    assert _capable_devices(db_session, job) == []


def test_model_metadata_seeded(seeded_db):
    m = seeded_db.query(EdgeCVModel).filter_by(model_name="mock-defect-candidate-detector").first()
    assert m is not None
    assert m.task_type == "defect_candidate_detection"
    assert m.model_format in C.MODEL_FORMATS
    assert m.target_device_type == "any"
