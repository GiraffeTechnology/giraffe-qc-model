"""Edge CV device service — registration, sessions, heartbeat, offline sweep.

The service layer is the source of truth (§5.2). An edge device never writes to
the DB; it only calls these functions (via the API routers). All device state
is derived here from heartbeats and TTL, so hot-plug/unplug never requires a
service restart (§5.1).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src import config
from src.db.models import _utcnow
from src.db.edge_cv_models import (
    EdgeCVDevice,
    EdgeCVDeviceMetric,
    EdgeCVDeviceSession,
)
from src.qc_model.edge_cv import constants as C
from src.qc_model.edge_cv.tokens import mint_device_token

# Degraded-state thresholds (§9.1 "degraded"). Conservative defaults; a device
# reporting resource pressure is still online but deprioritised by the dispatcher.
_DEGRADED_MEMORY_RATIO = 0.92
_DEGRADED_TEMPERATURE_C = 80.0
_DEGRADED_DISK_PERCENT = 95.0


class DeviceNotFound(Exception):
    pass


class InvalidSession(Exception):
    """Raised when a heartbeat/agent call presents a stale or unknown session."""


def _uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def as_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Coerce a DB datetime to timezone-aware UTC for safe comparison.

    ``DateTime(timezone=True)`` columns round-trip as aware on Postgres but come
    back *naive* from SQLite (no tz support). Assume naive values are UTC so
    lease/heartbeat comparisons against an aware ``now`` never raise on SQLite.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def register_device(
    db: Session,
    *,
    tenant_id: str = "default",
    device_name: str,
    device_type: str,
    serial_number: Optional[str] = None,
    mac_address: Optional[str] = None,
    ip_address: Optional[str] = None,
    agent_version: Optional[str] = None,
    capabilities: Optional[list[str]] = None,
    max_concurrent_jobs: int = 1,
) -> tuple[EdgeCVDevice, EdgeCVDeviceSession, str]:
    """Register (or re-register) a device and open a fresh session (§8.1, §8.4).

    Idempotent on ``(tenant_id, device_name)``: a returning device keeps its
    ``device_id`` but is issued a new ``session_id``. Any previously-active
    session for the device is closed, so leases owned by an old session become
    stale (§8.4) and cannot corrupt current state.

    Returns ``(device, session, device_token)``.
    """
    now = _utcnow()
    device = (
        db.query(EdgeCVDevice)
        .filter_by(tenant_id=tenant_id, device_name=device_name)
        .first()
    )
    if device is None:
        device = EdgeCVDevice(
            id=_uid("edge_dev_"),
            tenant_id=tenant_id,
            device_name=device_name,
            device_type=device_type,
            status=C.DEVICE_REGISTERING,
        )
        db.add(device)
    else:
        device.status = C.DEVICE_REGISTERING

    # Update mutable descriptors from the (re)registration.
    device.device_type = device_type
    device.serial_number = serial_number
    device.mac_address = mac_address
    device.ip_address = ip_address
    device.agent_version = agent_version
    device.capabilities_json = list(capabilities or [])
    device.max_concurrent_jobs = max(1, int(max_concurrent_jobs or 1))
    device.current_active_jobs = 0
    device.last_heartbeat_at = now
    device.last_seen_at = now
    device.updated_at = now
    db.flush()

    # Close any prior active sessions for this device (§8.4).
    prior = (
        db.query(EdgeCVDeviceSession)
        .filter_by(device_id=device.id, status="active")
        .all()
    )
    for sess in prior:
        sess.status = "ended"
        sess.ended_at = now
        sess.disconnect_reason = "superseded_by_new_session"

    session = EdgeCVDeviceSession(
        id=_uid("edge_sessrow_"),
        tenant_id=tenant_id,
        device_id=device.id,
        session_id=_uid("edge_sess_"),
        status="active",
        started_at=now,
        last_heartbeat_at=now,
    )
    db.add(session)

    # registering -> online: a freshly registered device is available.
    device.status = C.DEVICE_ONLINE
    db.commit()
    db.refresh(device)
    db.refresh(session)

    token = mint_device_token(device.id, session.session_id, tenant_id)
    return device, session, token


def _active_session(db: Session, device_id: str, session_id: str) -> Optional[EdgeCVDeviceSession]:
    return (
        db.query(EdgeCVDeviceSession)
        .filter_by(device_id=device_id, session_id=session_id, status="active")
        .first()
    )


def _derive_status(device: EdgeCVDevice, metrics: Optional[dict], active_job_count: int) -> str:
    """Derive online/busy/degraded from capacity + reported metrics."""
    if active_job_count >= device.max_concurrent_jobs:
        return C.DEVICE_BUSY
    if metrics:
        mem_used = metrics.get("memory_used_mb")
        mem_total = metrics.get("memory_total_mb")
        if mem_used and mem_total and mem_total > 0 and (mem_used / mem_total) >= _DEGRADED_MEMORY_RATIO:
            return C.DEVICE_DEGRADED
        temp = metrics.get("temperature_celsius")
        if temp is not None and temp >= _DEGRADED_TEMPERATURE_C:
            return C.DEVICE_DEGRADED
        disk = metrics.get("disk_used_percent")
        if disk is not None and disk >= _DEGRADED_DISK_PERCENT:
            return C.DEVICE_DEGRADED
    return C.DEVICE_ONLINE


def heartbeat(
    db: Session,
    *,
    device_id: str,
    session_id: str,
    status: str = "online",
    active_job_count: int = 0,
    metrics: Optional[dict] = None,
) -> EdgeCVDevice:
    """Record a heartbeat, refresh TTL, store metrics, derive status (§8.2, §8.3).

    Rejects a heartbeat from an unknown device or a non-active session
    (``InvalidSession``) so a stale session cannot keep a replaced device
    "alive". A device in ``maintenance`` stays in maintenance.
    """
    device = db.get(EdgeCVDevice, device_id)
    if device is None:
        raise DeviceNotFound(device_id)

    session = _active_session(db, device_id, session_id)
    if session is None:
        raise InvalidSession(session_id)

    now = _utcnow()
    device.last_heartbeat_at = now
    device.last_seen_at = now
    device.current_active_jobs = active_job_count
    session.last_heartbeat_at = now

    if metrics:
        db.add(
            EdgeCVDeviceMetric(
                id=_uid("edge_metric_"),
                tenant_id=device.tenant_id,
                device_id=device.id,
                session_id=session_id,
                cpu_usage_percent=metrics.get("cpu_usage_percent"),
                gpu_usage_percent=metrics.get("gpu_usage_percent"),
                memory_used_mb=metrics.get("memory_used_mb"),
                memory_total_mb=metrics.get("memory_total_mb"),
                temperature_celsius=metrics.get("temperature_celsius"),
                power_mode=metrics.get("power_mode"),
                disk_used_percent=metrics.get("disk_used_percent"),
                active_job_count=active_job_count,
            )
        )

    # Respect operator-imposed states; otherwise derive from health/capacity.
    if device.status not in (C.DEVICE_MAINTENANCE, C.DEVICE_ERROR):
        if status == "error":
            device.status = C.DEVICE_ERROR
        else:
            device.status = _derive_status(device, metrics, active_job_count)

    device.updated_at = now
    db.commit()
    db.refresh(device)
    return device


def sweep_offline_devices(db: Session, ttl_seconds: Optional[int] = None) -> list[EdgeCVDevice]:
    """Mark devices offline whose last heartbeat is older than the TTL (§8.3).

    Runs without any service restart. Devices in ``maintenance`` are left as-is
    (an operator disabled them deliberately). Returns the devices transitioned
    to offline. Their active sessions are closed with reason ``heartbeat_ttl``.
    """
    if ttl_seconds is None:
        ttl_seconds = config.edge_cv_heartbeat_ttl_seconds()
    cutoff = _utcnow() - timedelta(seconds=ttl_seconds)

    candidates = (
        db.query(EdgeCVDevice)
        .filter(EdgeCVDevice.status.notin_([C.DEVICE_OFFLINE, C.DEVICE_MAINTENANCE]))
        .all()
    )
    transitioned: list[EdgeCVDevice] = []
    for device in candidates:
        last_hb = as_aware_utc(device.last_heartbeat_at)
        if last_hb is None or last_hb < cutoff:
            device.status = C.DEVICE_OFFLINE
            device.updated_at = _utcnow()
            for sess in (
                db.query(EdgeCVDeviceSession)
                .filter_by(device_id=device.id, status="active")
                .all()
            ):
                sess.status = "ended"
                sess.ended_at = _utcnow()
                sess.disconnect_reason = "heartbeat_ttl"
            transitioned.append(device)
    if transitioned:
        db.commit()
    return transitioned


def list_devices(db: Session, tenant_id: str = "default") -> list[EdgeCVDevice]:
    return (
        db.query(EdgeCVDevice)
        .filter_by(tenant_id=tenant_id)
        .order_by(EdgeCVDevice.created_at.asc())
        .all()
    )


def get_device(db: Session, device_id: str, tenant_id: str = "default") -> EdgeCVDevice:
    device = db.get(EdgeCVDevice, device_id)
    if device is None or device.tenant_id != tenant_id:
        raise DeviceNotFound(device_id)
    return device


def disable_device(db: Session, device_id: str, tenant_id: str = "default") -> EdgeCVDevice:
    """Put a device into maintenance — no new jobs are assigned (§12.1)."""
    device = get_device(db, device_id, tenant_id)
    device.is_enabled = False
    device.status = C.DEVICE_MAINTENANCE
    device.updated_at = _utcnow()
    db.commit()
    db.refresh(device)
    return device


def enable_device(db: Session, device_id: str, tenant_id: str = "default") -> EdgeCVDevice:
    """Move a device out of maintenance. It must re-register to come online."""
    device = get_device(db, device_id, tenant_id)
    device.is_enabled = True
    # Not assumed reachable — it goes offline until the next heartbeat/register.
    device.status = C.DEVICE_OFFLINE
    device.updated_at = _utcnow()
    db.commit()
    db.refresh(device)
    return device


def device_view(device: EdgeCVDevice) -> dict:
    return {
        "device_id": device.id,
        "tenant_id": device.tenant_id,
        "device_name": device.device_name,
        "device_type": device.device_type,
        "status": device.status,
        "capabilities": device.capabilities_json or [],
        "max_concurrent_jobs": device.max_concurrent_jobs,
        "current_active_jobs": device.current_active_jobs,
        "is_enabled": device.is_enabled,
        "agent_version": device.agent_version,
        "last_heartbeat_at": device.last_heartbeat_at.isoformat() if device.last_heartbeat_at else None,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "created_at": device.created_at.isoformat() if device.created_at else None,
    }
