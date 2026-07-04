"""Unit tests: job creation, leasing, start, result upload, failure, lease
expiration, retry, CPU fallback, idempotency, invalid session, manual review
(§20.1)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from src.db.models import _utcnow
from src.db.edge_cv_models import CVJob, CVJobEvent, CVResult
from src.qc_model.edge_cv import constants as C
from src.qc_model.edge_cv import dispatcher, results, service, cpu_fallback
from src.qc_model.edge_cv.results import ResultRejected, ResultValidationError

from tests.edge_cv_helpers import db_session, seeded_db  # noqa: F401


def _register(db, name="jetson-a", caps=("defect_candidate_detection", "opencv"), max_jobs=1):
    return service.register_device(db, device_name=name, device_type="jetson_nano_2gb", capabilities=list(caps), max_concurrent_jobs=max_jobs)


def test_create_job_queues_and_writes_events(db_session):
    _register(db_session)  # a capable device exists → job stays queued
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    assert job.status == C.JOB_QUEUED
    events = db_session.query(CVJobEvent).filter_by(cv_job_id=job.id).all()
    kinds = {e.event_type for e in events}
    assert "created" in kinds and "queued" in kinds


def test_lease_start_result_completes_job(db_session):
    d, s, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    leased = dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
    assert leased.id == job.id and leased.status == C.JOB_LEASED
    dispatcher.mark_started(db_session, job_id=job.id, device_id=d.id, session_id=s.session_id)
    db_session.refresh(job)
    assert job.status == C.JOB_RUNNING
    results.upload_result(db_session, job_id=job.id, device_id=d.id, session_id=s.session_id, result_type="detection", pass_fail_hint="needs_human_review")
    db_session.refresh(job)
    assert job.status == C.JOB_COMPLETED
    assert db_session.query(CVResult).filter_by(cv_job_id=job.id).count() == 1


def test_leasing_marks_device_busy_at_capacity(db_session):
    d, s, _ = _register(db_session, max_jobs=1)
    dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
    db_session.refresh(d)
    assert d.status == C.DEVICE_BUSY and d.current_active_jobs == 1


def test_result_upload_persists_assets(db_session):
    d, s, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
    res = results.upload_result(
        db_session, job_id=job.id, device_id=d.id, session_id=s.session_id, result_type="detection",
        pass_fail_hint="needs_human_review",
        evidence_assets=[{"asset_type": "annotated_image", "asset_uri": "storage://a.jpg", "asset_hash": "sha256:x"}],
    )
    assert len(res.assets) == 1 and res.assets[0].asset_type == "annotated_image"


def test_idempotent_duplicate_result(db_session):
    d, s, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
    r1 = results.upload_result(db_session, job_id=job.id, device_id=d.id, session_id=s.session_id, result_type="detection", pass_fail_hint="unknown")
    r2 = results.upload_result(db_session, job_id=job.id, device_id=d.id, session_id=s.session_id, result_type="detection", pass_fail_hint="unknown")
    assert r1.id == r2.id
    assert db_session.query(CVResult).filter_by(cv_job_id=job.id).count() == 1


def test_stale_session_result_rejected(db_session):
    d, s1, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s1.session_id, capabilities=["defect_candidate_detection"])
    # Device reconnects → new session; the old session must not persist a result.
    service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb", capabilities=["defect_candidate_detection", "opencv"])
    with pytest.raises(ResultRejected):
        results.upload_result(db_session, job_id=job.id, device_id=d.id, session_id=s1.session_id, result_type="detection", pass_fail_hint="unknown")


def test_wrong_device_result_rejected(db_session):
    d, s, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
    with pytest.raises(ResultRejected):
        results.upload_result(db_session, job_id=job.id, device_id="edge_dev_other", session_id="edge_sess_other", result_type="detection")


def test_invalid_payload_moves_job_to_manual_review(db_session):
    d, s, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
    with pytest.raises(ResultValidationError):
        results.upload_result(db_session, job_id=job.id, device_id=d.id, session_id=s.session_id, result_type="detection", pass_fail_hint="bogus_hint")
    db_session.refresh(job)
    assert job.status == C.JOB_MANUAL_REVIEW


def test_unknown_asset_type_rejected(db_session):
    d, s, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
    with pytest.raises(ResultValidationError):
        results.upload_result(db_session, job_id=job.id, device_id=d.id, session_id=s.session_id, result_type="detection", pass_fail_hint="unknown", evidence_assets=[{"asset_type": "nope", "asset_uri": "x"}])


def test_lease_expiration_requeues_and_increments_retry(db_session, monkeypatch):
    d, s, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
    # Force the lease into the past.
    job.lease_expires_at = _utcnow() - timedelta(seconds=1)
    db_session.commit()
    affected = dispatcher.expire_leases(db_session)
    assert job.id in {j.id for j in affected}
    db_session.refresh(job)
    assert job.retry_count == 1
    # Device still online with capacity → job requeued (device slot released).
    db_session.refresh(d)
    assert d.current_active_jobs == 0
    assert job.status in (C.JOB_QUEUED, C.JOB_MANUAL_REVIEW)


def test_retry_exhaustion_goes_to_manual_review(db_session):
    d, s, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection", max_retries=1)
    # Simulate two lease expirations.
    for _ in range(2):
        db_session.refresh(job)
        if job.status == C.JOB_QUEUED:
            dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
        job.lease_expires_at = _utcnow() - timedelta(seconds=1)
        db_session.commit()
        dispatcher.expire_leases(db_session)
    db_session.refresh(job)
    assert job.status == C.JOB_MANUAL_REVIEW


def test_permanent_error_fails_immediately(db_session):
    d, s, _ = _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s.session_id, capabilities=["defect_candidate_detection"])
    dispatcher.fail_job(db_session, job_id=job.id, device_id=d.id, session_id=s.session_id, error_code="model_hash_mismatch", error_message="bad hash")
    db_session.refresh(job)
    assert job.status == C.JOB_MANUAL_REVIEW
    assert job.error_code == "model_hash_mismatch"


def test_cpu_fallback_completes_job_when_no_device(db_session):
    # No edge device registered → auto-dispatch runs CPU fallback.
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    db_session.refresh(job)
    assert job.status == C.JOB_COMPLETED
    res = db_session.query(CVResult).filter_by(cv_job_id=job.id).first()
    assert res is not None
    assert res.pass_fail_hint == "needs_human_review"  # QC never auto-passes
    assert res.confidence <= 0.5  # lower confidence than an edge result


def test_multiple_sequential_fallback_jobs_all_complete(db_session):
    # Regression: the CPU fallback runner is server-side, not a pull agent, so a
    # second no-device job must also fall back — never hang in `queued` waiting
    # for the phantom cpu-runner to pull it.
    j1 = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    j2 = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    db_session.refresh(j1)
    db_session.refresh(j2)
    assert j1.status == C.JOB_COMPLETED
    assert j2.status == C.JOB_COMPLETED


def test_cpu_fallback_disabled_marks_manual_review(db_session, monkeypatch):
    monkeypatch.setenv("EDGE_CV_CPU_FALLBACK", "false")
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    db_session.refresh(job)
    assert job.status == C.JOB_MANUAL_REVIEW


def test_cancel_job(db_session):
    _register(db_session)
    job = dispatcher.create_job(db_session, task_type="defect_candidate_detection")
    dispatcher.cancel_job(db_session, job.id)
    db_session.refresh(job)
    assert job.status == C.JOB_CANCELLED


def test_pull_with_stale_session_raises(db_session):
    d, s1, _ = _register(db_session)
    service.register_device(db_session, device_name="jetson-a", device_type="jetson_nano_2gb", capabilities=["defect_candidate_detection", "opencv"])
    from src.qc_model.edge_cv.dispatcher import InvalidJobState
    with pytest.raises(InvalidJobState):
        dispatcher.lease_next_job_for_device(db_session, device_id=d.id, session_id=s1.session_id, capabilities=["defect_candidate_detection"])
