"""HTTP API for the Jetson Xavier NX inference runner (server side).

Admin / Pad-sync surface under ``/api/qc/jetson`` (same auth surface as the
S3 workstation APIs). The Jetson never calls these — the Pad relays the pairing
binding and health on sync, and admins view fleet/readiness state. Inference
itself is a Pad↔Jetson LAN call and does not pass through the Server.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.qc_model.jetson import constants as C
from src.qc_model.jetson import service
from src.qc_model.jetson.contract import validate_request
from src.qc_model.jetson.service import RunnerNotFound, WorkstationNotFound

router = APIRouter(tags=["qc-jetson"])


class ProvisionBody(BaseModel):
    tenant_id: str = "default"
    jetson_device_id: str
    pubkey_fingerprint: str
    agent_version: Optional[str] = None


class BindingBody(BaseModel):
    tenant_id: str = "default"
    jetson_device_id: str
    pubkey_fingerprint: str
    workstation_id: str
    pad_device_id: str
    pairing_path: str
    agent_version: Optional[str] = None
    paired_at: Optional[str] = None


class HealthBody(BaseModel):
    tenant_id: str = "default"
    jetson_device_id: str
    service_up: Optional[bool] = None
    model_loaded: Optional[bool] = None
    temperature_c: Optional[float] = None
    throttling: Optional[bool] = None
    disk_free_percent: Optional[float] = None
    last_inference_latency_ms: Optional[int] = None
    readiness_state: Optional[str] = None


class ReadinessQuery(BaseModel):
    sku_selected: bool
    standard_installed: bool
    jetson_reachable: bool
    service_up: bool = False
    model_loaded: bool = False


@router.post("/api/qc/jetson/runners", status_code=201)
def provision(body: ProvisionBody, db: Session = Depends(get_db_dep)):
    runner = service.provision_runner(
        db,
        tenant_id=body.tenant_id,
        jetson_device_id=body.jetson_device_id,
        pubkey_fingerprint=body.pubkey_fingerprint,
        agent_version=body.agent_version,
    )
    return service.runner_view(db, runner)


@router.get("/api/qc/jetson/runners")
def list_runners(tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    return [service.runner_view(db, r) for r in service.list_runners(db, tenant_id)]


@router.get("/api/qc/jetson/runners/{jetson_device_id}")
def read_runner(jetson_device_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        return service.runner_view(db, service.get_runner(db, tenant_id, jetson_device_id))
    except RunnerNotFound:
        raise HTTPException(status_code=404, detail="jetson_runner_not_found")


@router.post("/api/qc/jetson/bindings", status_code=201)
def register_binding(body: BindingBody, db: Session = Depends(get_db_dep)):
    """Pad-reported pairing binding (offline-tolerant sync)."""
    paired_at = None
    if body.paired_at:
        try:
            paired_at = datetime.fromisoformat(body.paired_at)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid paired_at (expected ISO 8601)")
    try:
        runner = service.register_binding(
            db,
            tenant_id=body.tenant_id,
            jetson_device_id=body.jetson_device_id,
            pubkey_fingerprint=body.pubkey_fingerprint,
            workstation_id=body.workstation_id,
            pad_device_id=body.pad_device_id,
            pairing_path=body.pairing_path,
            agent_version=body.agent_version,
            paired_at=paired_at,
        )
    except WorkstationNotFound:
        raise HTTPException(status_code=404, detail="workstation_not_found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return service.runner_view(db, runner)


@router.post("/api/qc/jetson/runners/{jetson_device_id}/unpair", status_code=200)
def unpair(jetson_device_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        runner = service.unpair(db, tenant_id=tenant_id, jetson_device_id=jetson_device_id)
    except RunnerNotFound:
        raise HTTPException(status_code=404, detail="jetson_runner_not_found")
    return service.runner_view(db, runner)


@router.post("/api/qc/jetson/runners/{jetson_device_id}/health", status_code=200)
def report_health(jetson_device_id: str, body: HealthBody, db: Session = Depends(get_db_dep)):
    try:
        runner = service.report_health(
            db,
            tenant_id=body.tenant_id,
            jetson_device_id=jetson_device_id,
            service_up=body.service_up,
            model_loaded=body.model_loaded,
            temperature_c=body.temperature_c,
            throttling=body.throttling,
            disk_free_percent=body.disk_free_percent,
            last_inference_latency_ms=body.last_inference_latency_ms,
            readiness_state=body.readiness_state,
        )
    except RunnerNotFound:
        raise HTTPException(status_code=404, detail="jetson_runner_not_found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return service.runner_view(db, runner)


@router.post("/api/qc/jetson/readiness")
def readiness(body: ReadinessQuery):
    """Resolve the operator-facing readiness state (§5) + submit gate."""
    state = service.resolve_readiness(
        sku_selected=body.sku_selected,
        standard_installed=body.standard_installed,
        jetson_reachable=body.jetson_reachable,
        service_up=body.service_up,
        model_loaded=body.model_loaded,
    )
    return {
        "readiness_state": state,
        "readiness_label": C.READINESS_LABELS.get(state),
        "can_submit_inspection": service.can_submit_inspection(state),
    }


@router.post("/api/qc/jetson/inference/validate")
def validate_inference_request(payload: dict):
    """Validate a Pad→Jetson inference request against the §4 contract.

    A helper for Pad developers / integration tests — the Server is not in the
    inference path, but it owns the canonical contract definition.
    """
    from pydantic import ValidationError

    try:
        req = validate_request(payload)
    except ValidationError as exc:
        # Return a JSON-serializable summary (pydantic error ctx can hold a
        # raw exception object that is not JSON serializable).
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        raise HTTPException(status_code=422, detail=errors)
    return {"valid": True, "job_id": req.job_id, "detection_point_count": len(req.detection_points)}
