"""CV job dispatcher — creation, device selection, leasing, lease expiration.

Job acquisition is *pull-based* (§5.3): an online edge device asks for work via
``lease_next_job_for_device`` and the service hands it a matching queued job
under a time-bounded lease. The service never opens a connection to a device.

CPU fallback (§5.4, §15) keeps the workflow moving when no capable edge device
is available — see :mod:`src.qc_model.edge_cv.cpu_fallback`. Lease expiration
(§13.2) makes hot-unplug failure-safe: a job whose device vanished is requeued,
fallback-processed, or escalated to manual review — never silently lost.
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from src import config
from src.db.models import _utcnow
from src.db.edge_cv_models import CVJob, CVJobEvent, EdgeCVDevice, EdgeCVModel
from src.qc_model.edge_cv import constants as C
from src.qc_model.edge_cv.service import _active_session


class JobNotFound(Exception):
    pass


class InvalidJobState(Exception):
    pass


def _uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def record_event(
    db: Session,
    job: CVJob,
    *,
    from_status: Optional[str],
    to_status: Optional[str],
    event_type: str,
    payload: Optional[dict] = None,
    created_by: Optional[str] = None,
) -> CVJobEvent:
    """Append one audit event for a job (every transition writes one — §11.5)."""
    event = CVJobEvent(
        id=_uid("cv_evt_"),
        cv_job_id=job.id,
        tenant_id=job.tenant_id,
        from_status=from_status,
        to_status=to_status,
        event_type=event_type,
        event_payload_json=payload,
        created_by=created_by,
    )
    db.add(event)
    return event


def _transition(
    db: Session,
    job: CVJob,
    to_status: str,
    *,
    event_type: str = "state_transition",
    payload: Optional[dict] = None,
    created_by: Optional[str] = None,
) -> None:
    from_status = job.status
    job.status = to_status
    job.updated_at = _utcnow()
    record_event(
        db,
        job,
        from_status=from_status,
        to_status=to_status,
        event_type=event_type,
        payload=payload,
        created_by=created_by,
    )


def resolve_model_for_task(db: Session, tenant_id: str, task_type: str) -> Optional[EdgeCVModel]:
    """Pick an active model for a task type (tenant-scoped, newest first)."""
    return (
        db.query(EdgeCVModel)
        .filter_by(tenant_id=tenant_id, task_type=task_type, is_active=True)
        .order_by(EdgeCVModel.created_at.desc())
        .first()
    )


def create_job(
    db: Session,
    *,
    tenant_id: str = "default",
    task_type: str,
    source_asset_id: Optional[str] = None,
    inspection_id: Optional[str] = None,
    requested_by: Optional[str] = None,
    priority: str = "normal",
    input_payload: Optional[dict] = None,
    max_retries: Optional[int] = None,
    auto_dispatch: bool = True,
) -> CVJob:
    """Create a CV job (pending -> queued) and optionally dispatch it (§10, §13).

    When ``auto_dispatch`` is set (default) the job is immediately routed:
    * if a capable online edge device exists → the job stays ``queued`` for that
      device to pull (pull-based acquisition);
    * else if CPU fallback is enabled → it is processed by the CPU runner now;
    * else → it is escalated to ``manual_review_required`` (QC never silently
      freezes — §5.4, §10.3).
    """
    if task_type not in C.TASK_TYPES:
        raise InvalidJobState(f"unknown task_type: {task_type}")

    now = _utcnow()
    model = resolve_model_for_task(db, tenant_id, task_type)
    job = CVJob(
        id=_uid("cv_job_"),
        tenant_id=tenant_id,
        source_asset_id=source_asset_id,
        inspection_id=inspection_id,
        requested_by=requested_by,
        task_type=task_type,
        priority=priority if priority in ("low", "normal", "high") else "normal",
        status=C.JOB_PENDING,
        model_id=model.id if model else None,
        input_payload_json=input_payload or {},
        max_retries=config.edge_cv_max_retries() if max_retries is None else max_retries,
        created_at=now,
    )
    db.add(job)
    record_event(db, job, from_status=None, to_status=C.JOB_PENDING, event_type="created", created_by=requested_by)

    # pending -> queued
    job.queued_at = now
    _transition(db, job, C.JOB_QUEUED, event_type="queued")
    db.commit()
    db.refresh(job)

    if auto_dispatch:
        dispatch_job(db, job)
        db.refresh(job)
    return job


def _capable_devices(db: Session, job: CVJob) -> list[EdgeCVDevice]:
    """Enabled, dispatchable, capacity-available devices matching the job (§13.1).

    Filters by required capabilities (the job's task type must be advertised),
    ``current_active_jobs < max_concurrent_jobs``, and model/device-type
    compatibility. Sorted: online before degraded, least-busy first, most
    recently seen first.
    """
    model = db.get(EdgeCVModel, job.model_id) if job.model_id else None
    required_caps = set(model.required_capabilities_json or []) if model else set()
    required_caps.add(job.task_type)

    devices = (
        db.query(EdgeCVDevice)
        .filter(
            EdgeCVDevice.tenant_id == job.tenant_id,
            EdgeCVDevice.is_enabled.is_(True),
            EdgeCVDevice.status.in_(list(C.DEVICE_DISPATCHABLE_STATES)),
            # The CPU fallback runner is a server-side worker, not a pull-based
            # agent — it must never count as an "available device" that would
            # leave a job queued waiting for a puller that does not exist.
            EdgeCVDevice.device_type != C.DEVICE_TYPE_CPU_RUNNER,
        )
        .all()
    )

    matched: list[EdgeCVDevice] = []
    for d in devices:
        caps = set(d.capabilities_json or [])
        if not required_caps.issubset(caps):
            continue
        if d.current_active_jobs >= d.max_concurrent_jobs:
            continue
        if model and model.target_device_type not in ("any", d.device_type):
            continue
        matched.append(d)

    def _sort_key(d: EdgeCVDevice):
        status_rank = 0 if d.status == C.DEVICE_ONLINE else 1
        last_hb = d.last_heartbeat_at.timestamp() if d.last_heartbeat_at else 0.0
        return (status_rank, d.current_active_jobs, -last_hb)

    matched.sort(key=_sort_key)
    return matched


def has_capable_device(db: Session, job: CVJob) -> bool:
    return bool(_capable_devices(db, job))


def dispatch_job(db: Session, job: CVJob) -> CVJob:
    """Route a queued job to an edge device (pull) or CPU fallback (§13, §24.1).

    Idempotent for non-queued jobs (already leased/terminal → no-op).
    """
    if job.status != C.JOB_QUEUED:
        return job

    if has_capable_device(db, job):
        # A capable device exists; leave the job queued for it to pull.
        return job

    # No capable edge device online.
    from src.qc_model.edge_cv import cpu_fallback

    if config.edge_cv_cpu_fallback():
        cpu_fallback.run_cpu_fallback(db, job)
    else:
        _transition(
            db,
            job,
            C.JOB_MANUAL_REVIEW,
            event_type="no_device_no_fallback",
            payload={"reason": "no capable edge device and CPU fallback disabled"},
        )
        db.commit()
    db.refresh(job)
    return job


def lease_next_job_for_device(
    db: Session,
    *,
    device_id: str,
    session_id: str,
    capabilities: Optional[list[str]] = None,
) -> Optional[CVJob]:
    """Pull the next queued job for a device and lease it (§12.3, §10.2).

    Returns the leased job (``queued -> leased``) or ``None`` when nothing
    matches. Validates the device + active session, enforces capacity, and only
    hands out jobs whose required capabilities the device advertises.
    """
    device = db.get(EdgeCVDevice, device_id)
    if device is None:
        return None
    session = _active_session(db, device_id, session_id)
    if session is None:
        raise InvalidJobState("stale_or_unknown_session")
    if not device.is_enabled or device.status not in C.DEVICE_DISPATCHABLE_STATES:
        return None
    if device.current_active_jobs >= device.max_concurrent_jobs:
        return None

    advertised = set(capabilities or device.capabilities_json or [])

    candidates = (
        db.query(CVJob)
        .filter(CVJob.tenant_id == device.tenant_id, CVJob.status == C.JOB_QUEUED)
        .order_by(CVJob.priority.desc(), CVJob.created_at.asc())
        .all()
    )
    for job in candidates:
        model = db.get(EdgeCVModel, job.model_id) if job.model_id else None
        required_caps = set(model.required_capabilities_json or []) if model else set()
        required_caps.add(job.task_type)
        if not required_caps.issubset(advertised):
            continue
        if model and model.target_device_type not in ("any", device.device_type):
            continue

        now = _utcnow()
        lease_expires = now + timedelta(seconds=config.edge_cv_job_lease_seconds())
        job.assigned_device_id = device.id
        job.assigned_session_id = session_id
        job.lease_owner_device_id = device.id
        job.lease_owner_session_id = session_id
        job.lease_expires_at = lease_expires
        job.leased_at = now
        _transition(
            db,
            job,
            C.JOB_LEASED,
            event_type="leased",
            payload={"device_id": device.id, "session_id": session_id},
            created_by=device.id,
        )
        device.current_active_jobs += 1
        if device.current_active_jobs >= device.max_concurrent_jobs and device.status == C.DEVICE_ONLINE:
            device.status = C.DEVICE_BUSY
        device.updated_at = now
        db.commit()
        db.refresh(job)
        return job
    return None


def mark_started(db: Session, *, job_id: str, device_id: str, session_id: str) -> CVJob:
    """Mark a leased job as running (§12.3 start). Validates lease ownership."""
    job = db.get(CVJob, job_id)
    if job is None:
        raise JobNotFound(job_id)
    _assert_lease_owner(job, device_id, session_id)
    if job.status not in (C.JOB_LEASED, C.JOB_RUNNING):
        raise InvalidJobState(f"cannot start job in status {job.status}")
    if job.status == C.JOB_LEASED:
        job.started_at = _utcnow()
        _transition(db, job, C.JOB_RUNNING, event_type="started", created_by=device_id)
        db.commit()
        db.refresh(job)
    return job


def _assert_lease_owner(job: CVJob, device_id: str, session_id: str) -> None:
    if job.lease_owner_device_id != device_id or job.lease_owner_session_id != session_id:
        # Stale session / wrong device — never mutate current state (§8.4, §17.3).
        raise InvalidJobState("lease_not_owned_by_caller")


def _release_device_slot(db: Session, device_id: Optional[str]) -> None:
    if not device_id:
        return
    device = db.get(EdgeCVDevice, device_id)
    if device is None:
        return
    if device.current_active_jobs > 0:
        device.current_active_jobs -= 1
    if device.status == C.DEVICE_BUSY and device.current_active_jobs < device.max_concurrent_jobs:
        device.status = C.DEVICE_ONLINE
    device.updated_at = _utcnow()


def _requeue_or_escalate(
    db: Session,
    job: CVJob,
    *,
    event_type: str,
    reason: str,
    permanent: bool = False,
) -> None:
    """Increment retry and move to retry_scheduled/queued or terminal state.

    Under the retry limit → requeue (retry_scheduled -> queued). Over the limit,
    or a permanent error → ``manual_review_required`` (QC default, §10.3): QC
    must never silently fail.
    """
    _release_device_slot(db, job.lease_owner_device_id)
    job.assigned_device_id = None
    job.assigned_session_id = None
    job.lease_owner_device_id = None
    job.lease_owner_session_id = None
    job.lease_expires_at = None

    if not permanent and job.retry_count < job.max_retries:
        job.retry_count += 1
        _transition(
            db,
            job,
            C.JOB_RETRY_SCHEDULED,
            event_type=event_type,
            payload={"reason": reason, "retry_count": job.retry_count},
        )
        # Immediately re-queue for another attempt.
        job.queued_at = _utcnow()
        _transition(db, job, C.JOB_QUEUED, event_type="requeued")
    else:
        job.retry_count += 1
        job.error_code = job.error_code or ("permanent_error" if permanent else "retry_exhausted")
        _transition(
            db,
            job,
            C.JOB_MANUAL_REVIEW,
            event_type=event_type,
            payload={"reason": reason, "retry_count": job.retry_count, "permanent": permanent},
        )


def expire_leases(db: Session) -> list[CVJob]:
    """Expire leases past their deadline and recover the jobs (§13.2).

    Runs periodically with no service restart. For each expired lease: write an
    event, increment retry, clear assignment, then requeue or escalate. After
    requeue, an attempt is made to dispatch (CPU fallback when no device).
    Returns the affected jobs.
    """
    now = _utcnow()
    expired = (
        db.query(CVJob)
        .filter(
            CVJob.status.in_(list(C.JOB_LEASED_STATES)),
            CVJob.lease_expires_at.isnot(None),
            CVJob.lease_expires_at < now,
        )
        .all()
    )
    affected: list[CVJob] = []
    for job in expired:
        _requeue_or_escalate(db, job, event_type="lease_expired", reason="lease_expired")
        affected.append(job)
    if affected:
        db.commit()
        # Recover any requeued jobs (CPU fallback if no device is available).
        for job in affected:
            db.refresh(job)
            if job.status == C.JOB_QUEUED:
                dispatch_job(db, job)
    return affected


def cancel_job(db: Session, job_id: str, tenant_id: str = "default", created_by: Optional[str] = None) -> CVJob:
    job = db.get(CVJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise JobNotFound(job_id)
    if job.status in C.JOB_TERMINAL_STATES:
        raise InvalidJobState(f"job already terminal: {job.status}")
    _release_device_slot(db, job.lease_owner_device_id)
    job.lease_owner_device_id = None
    job.lease_owner_session_id = None
    job.lease_expires_at = None
    job.cancelled_at = _utcnow()
    _transition(db, job, C.JOB_CANCELLED, event_type="cancelled", created_by=created_by)
    db.commit()
    db.refresh(job)
    return job


def fail_job(
    db: Session,
    *,
    job_id: str,
    device_id: str,
    session_id: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> CVJob:
    """Agent-reported failure (§12.3 fail). Validates lease ownership.

    A permanent error (e.g. ``model_hash_mismatch``) fails the job for review
    immediately; a transient one is retried within the retry budget.
    """
    job = db.get(CVJob, job_id)
    if job is None:
        raise JobNotFound(job_id)
    _assert_lease_owner(job, device_id, session_id)

    job.error_code = error_code
    job.error_message = error_message
    permanent = error_code in C.PERMANENT_ERROR_CODES
    _requeue_or_escalate(
        db,
        job,
        event_type="agent_failed",
        reason=error_code or "agent_failed",
        permanent=permanent,
    )
    db.commit()
    db.refresh(job)
    if job.status == C.JOB_QUEUED:
        dispatch_job(db, job)
        db.refresh(job)
    return job


def job_view(db: Session, job: CVJob) -> dict:
    from src.db.edge_cv_models import CVResult

    results = (
        db.query(CVResult).filter_by(cv_job_id=job.id).order_by(CVResult.created_at.asc()).all()
    )
    return {
        "cv_job_id": job.id,
        "tenant_id": job.tenant_id,
        "task_type": job.task_type,
        "status": job.status,
        "priority": job.priority,
        "source_asset_id": job.source_asset_id,
        "inspection_id": job.inspection_id,
        "model_id": job.model_id,
        "assigned_device_id": job.assigned_device_id,
        "assigned_session_id": job.assigned_session_id,
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "input_payload": job.input_payload_json or {},
        "result_ids": [r.id for r in results],
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }
