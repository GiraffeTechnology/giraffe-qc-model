"""Server-side Jetson runner service: provisioning, binding, health, readiness.

The Jetson never calls these — the **Pad** does, on sync (offline-tolerant: the
floor pairs first, the Server learns about it later). The Server is the record of
the current 1:1 binding and the health the Pad surfaces on its UI. It is not in
the inference path (Pad↔Jetson LAN) and never trusts Jetson output as a verdict.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import _utcnow
from src.db.qc_bundle_models import QCWorkstation
from src.db.qc_jetson_models import QCJetsonPairingEvent, QCJetsonRunner
from src.qc_model.jetson import constants as C


class RunnerNotFound(Exception):
    pass


class WorkstationNotFound(Exception):
    pass


def _uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def _event(db: Session, runner: QCJetsonRunner, event_type: str, **fields) -> None:
    db.add(
        QCJetsonPairingEvent(
            id=_uid("jetevt_"),
            tenant_id=runner.tenant_id,
            runner_pk=runner.id,
            event_type=event_type,
            pairing_path=fields.get("pairing_path"),
            workstation_id=fields.get("workstation_id"),
            pad_device_id=fields.get("pad_device_id"),
            detail_json=fields.get("detail"),
        )
    )


def provision_runner(
    db: Session,
    *,
    tenant_id: str = "default",
    jetson_device_id: str,
    pubkey_fingerprint: str,
    agent_version: Optional[str] = None,
) -> QCJetsonRunner:
    """Register a provisioned Jetson identity (idempotent on device id).

    Provisioning happens off-floor (bench setup with monitor/SSH is fine there);
    this records the identity + chassis fingerprint so Path B verification and
    admin visibility work. Returns the existing runner if already provisioned.
    """
    runner = (
        db.query(QCJetsonRunner)
        .filter_by(tenant_id=tenant_id, jetson_device_id=jetson_device_id)
        .first()
    )
    if runner is not None:
        # Keep the fingerprint/version fresh but never silently re-key a paired
        # device: identity changes are out of scope for this call.
        runner.agent_version = agent_version or runner.agent_version
        db.commit()
        db.refresh(runner)
        return runner

    runner = QCJetsonRunner(
        id=_uid("jetrun_"),
        tenant_id=tenant_id,
        jetson_device_id=jetson_device_id,
        pubkey_fingerprint=pubkey_fingerprint,
        agent_version=agent_version,
        pairing_status=C.PAIRING_UNPAIRED,
    )
    db.add(runner)
    db.flush()
    _event(db, runner, C.EVENT_PROVISIONED, detail={"fingerprint": pubkey_fingerprint})
    db.commit()
    db.refresh(runner)
    return runner


def register_binding(
    db: Session,
    *,
    tenant_id: str = "default",
    jetson_device_id: str,
    pubkey_fingerprint: str,
    workstation_id: str,
    pad_device_id: str,
    pairing_path: str,
    agent_version: Optional[str] = None,
    paired_at: Optional[datetime] = None,
) -> QCJetsonRunner:
    """Record a Pad-reported Pad↔Jetson pairing binding (§2, addendum §1).

    Enforces the 1:1 rule fail-closed: a Jetson bound elsewhere is re-bound here
    (its previous binding is dropped), and a workstation already bound to a
    *different* Jetson has that other Jetson unbound. Re-pairing replaces the
    previous binding with no grace period — the Server record always reflects
    exactly one current Pad↔Jetson pair.

    Auto-provisions the runner if the Server has not seen it (sync tolerance).
    """
    if pairing_path not in C.PAIRING_PATHS:
        raise ValueError(f"invalid pairing_path: {pairing_path}")

    workstation = (
        db.query(QCWorkstation)
        .filter_by(tenant_id=tenant_id, workstation_id=workstation_id)
        .first()
    )
    if workstation is None:
        raise WorkstationNotFound(workstation_id)

    runner = (
        db.query(QCJetsonRunner)
        .filter_by(tenant_id=tenant_id, jetson_device_id=jetson_device_id)
        .first()
    )
    if runner is None:
        runner = provision_runner(
            db,
            tenant_id=tenant_id,
            jetson_device_id=jetson_device_id,
            pubkey_fingerprint=pubkey_fingerprint,
            agent_version=agent_version,
        )

    now = _utcnow()

    # Free the target workstation from any *other* Jetson it was bound to.
    others = (
        db.query(QCJetsonRunner)
        .filter(
            QCJetsonRunner.tenant_id == tenant_id,
            QCJetsonRunner.workstation_pk == workstation.id,
            QCJetsonRunner.id != runner.id,
            QCJetsonRunner.pairing_status == C.PAIRING_PAIRED,
        )
        .all()
    )
    for other in others:
        other.pairing_status = C.PAIRING_UNPAIRED
        other.workstation_pk = None
        other.paired_pad_device_id = None
        other.unpaired_at = now
        _event(db, other, C.EVENT_UNPAIRED, detail={"reason": "workstation_rebound"})

    was_paired = runner.pairing_status == C.PAIRING_PAIRED
    rebind = was_paired and (
        runner.workstation_pk != workstation.id or runner.paired_pad_device_id != pad_device_id
    )

    runner.pairing_status = C.PAIRING_PAIRED
    runner.pairing_path = pairing_path
    runner.workstation_pk = workstation.id
    runner.paired_pad_device_id = pad_device_id
    runner.paired_at = paired_at or now
    runner.unpaired_at = None
    runner.agent_version = agent_version or runner.agent_version
    runner.last_seen_at = now

    # Mirror the pairing onto the workstation record (Pad + Jetson binding).
    workstation.paired_status = "paired"

    _event(
        db,
        runner,
        C.EVENT_REPAIRED if rebind else C.EVENT_PAIRED,
        pairing_path=pairing_path,
        workstation_id=workstation_id,
        pad_device_id=pad_device_id,
    )
    db.commit()
    db.refresh(runner)
    return runner


def unpair(db: Session, *, tenant_id: str = "default", jetson_device_id: str) -> QCJetsonRunner:
    """Drop a Jetson's binding (fail-closed: no grace)."""
    runner = _get(db, tenant_id, jetson_device_id)
    runner.pairing_status = C.PAIRING_UNPAIRED
    runner.workstation_pk = None
    runner.paired_pad_device_id = None
    runner.unpaired_at = _utcnow()
    _event(db, runner, C.EVENT_UNPAIRED)
    db.commit()
    db.refresh(runner)
    return runner


def report_health(
    db: Session,
    *,
    tenant_id: str = "default",
    jetson_device_id: str,
    service_up: Optional[bool] = None,
    model_loaded: Optional[bool] = None,
    temperature_c: Optional[float] = None,
    throttling: Optional[bool] = None,
    disk_free_percent: Optional[float] = None,
    last_inference_latency_ms: Optional[int] = None,
    readiness_state: Optional[str] = None,
) -> QCJetsonRunner:
    """Record Jetson health the Pad relayed (§6.1). All fields optional."""
    runner = _get(db, tenant_id, jetson_device_id)
    now = _utcnow()
    if service_up is not None:
        runner.service_up = service_up
    if model_loaded is not None:
        runner.model_loaded = model_loaded
    if temperature_c is not None:
        runner.temperature_c = temperature_c
    if throttling is not None:
        runner.throttling = throttling
    if disk_free_percent is not None:
        runner.disk_free_percent = disk_free_percent
    if last_inference_latency_ms is not None:
        runner.last_inference_latency_ms = last_inference_latency_ms
    if readiness_state is not None:
        if readiness_state not in C.READINESS_STATES:
            raise ValueError(f"invalid readiness_state: {readiness_state}")
        runner.readiness_state = readiness_state
    runner.last_seen_at = now
    runner.health_reported_at = now
    _event(db, runner, C.EVENT_HEALTH, detail={"readiness": readiness_state})
    db.commit()
    db.refresh(runner)
    return runner


def resolve_readiness(
    *,
    sku_selected: bool,
    standard_installed: bool,
    jetson_reachable: bool,
    service_up: bool = False,
    model_loaded: bool = False,
) -> str:
    """Compute the operator-facing readiness state (§5), fail-closed.

    Order matters: an operator needs the *actionable* blocker. Missing SKU and
    standard are pre-conditions; then Jetson reachability (fail-closed — an
    unreachable Jetson blocks submission entirely).
    """
    if not sku_selected:
        return C.NO_SKU
    if not standard_installed:
        return C.NO_STANDARD
    if not jetson_reachable:
        return C.UNREACHABLE
    if not (service_up and model_loaded):
        return C.CONNECTING
    return C.READY


def can_submit_inspection(readiness_state: str) -> bool:
    """Fail-closed: only a fully-ready Jetson permits inspection submission."""
    return readiness_state in C.SUBMITTABLE_STATES


def _get(db: Session, tenant_id: str, jetson_device_id: str) -> QCJetsonRunner:
    runner = (
        db.query(QCJetsonRunner)
        .filter_by(tenant_id=tenant_id, jetson_device_id=jetson_device_id)
        .first()
    )
    if runner is None:
        raise RunnerNotFound(jetson_device_id)
    return runner


def get_runner(db: Session, tenant_id: str, jetson_device_id: str) -> QCJetsonRunner:
    return _get(db, tenant_id, jetson_device_id)


def list_runners(db: Session, tenant_id: str = "default") -> list[QCJetsonRunner]:
    return (
        db.query(QCJetsonRunner)
        .filter_by(tenant_id=tenant_id)
        .order_by(QCJetsonRunner.created_at.asc())
        .all()
    )


def runner_view(db: Session, runner: QCJetsonRunner) -> dict:
    workstation_id = None
    if runner.workstation_pk:
        ws = db.get(QCWorkstation, runner.workstation_pk)
        workstation_id = ws.workstation_id if ws else None
    return {
        "jetson_device_id": runner.jetson_device_id,
        "tenant_id": runner.tenant_id,
        "pubkey_fingerprint": runner.pubkey_fingerprint,
        "agent_version": runner.agent_version,
        "pairing_status": runner.pairing_status,
        "pairing_path": runner.pairing_path,
        "workstation_id": workstation_id,
        "paired_pad_device_id": runner.paired_pad_device_id,
        "paired_at": runner.paired_at.isoformat() if runner.paired_at else None,
        "health": {
            "readiness_state": runner.readiness_state,
            "readiness_label": C.READINESS_LABELS.get(runner.readiness_state),
            "service_up": runner.service_up,
            "model_loaded": runner.model_loaded,
            "temperature_c": runner.temperature_c,
            "throttling": runner.throttling,
            "disk_free_percent": runner.disk_free_percent,
            "last_inference_latency_ms": runner.last_inference_latency_ms,
            "last_seen_at": runner.last_seen_at.isoformat() if runner.last_seen_at else None,
            "health_reported_at": runner.health_reported_at.isoformat() if runner.health_reported_at else None,
        },
    }
