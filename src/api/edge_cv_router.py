"""HTTP API for the hot-pluggable Edge CV subsystem.

Three groups of endpoints:

* **Device APIs** (``/api/edge-cv/devices/*``) — registration, heartbeat,
  list/read, enable/disable.
* **Edge-agent job APIs** (``/api/edge-cv/jobs/*`` and ``/api/edge-cv/captures/*``)
  — pull-based job acquisition, start/result/fail, and live-capture upload.
  These require a service-issued **device token** (§17.2) whose signed
  device/session claims must match the request body.
* **Operator/admin CV job APIs** (``/api/cv/jobs/*``) — create/read/cancel.

The whole subsystem is optional: when ``EDGE_CV_ENABLED=false`` every endpoint
returns ``503`` so the rest of the system behaves exactly as before (§23.4).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src import config
from src.api.deps import get_db_dep
from src.qc_model.edge_cv import captures, dispatcher, results
from src.qc_model.edge_cv import service as device_service
from src.qc_model.edge_cv.captures import CaptureRejected
from src.qc_model.edge_cv.dispatcher import InvalidJobState, JobNotFound
from src.qc_model.edge_cv.results import ResultRejected, ResultValidationError
from src.qc_model.edge_cv.service import DeviceNotFound, InvalidSession
from src.qc_model.edge_cv.tokens import verify_device_token

router = APIRouter(tags=["edge-cv"])


def _require_enabled() -> None:
    if not config.edge_cv_enabled():
        raise HTTPException(status_code=503, detail="edge_cv_disabled")


def require_device_token(authorization: Optional[str] = Header(default=None)) -> dict:
    """Resolve + require a valid device token; return its claims (§17.2)."""
    _require_enabled()
    if not authorization:
        raise HTTPException(status_code=401, detail="device token required", headers={"WWW-Authenticate": "Bearer"})
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        raise HTTPException(status_code=401, detail="invalid authorization scheme")
    claims = verify_device_token(value.strip())
    if claims is None:
        raise HTTPException(status_code=401, detail="invalid device token")
    return claims


def _assert_identity(claims: dict, device_id: str, session_id: str) -> None:
    """The token's signed device/session must match the request body (§17.3)."""
    if claims["device_id"] != device_id or claims["session_id"] != session_id:
        raise HTTPException(status_code=403, detail="token identity mismatch")


# ── Request models ───────────────────────────────────────────────────────────
class RegisterBody(BaseModel):
    tenant_id: str = "default"
    device_name: str
    device_type: str
    serial_number: Optional[str] = None
    mac_address: Optional[str] = None
    agent_version: Optional[str] = None
    capabilities: list[str] = []
    max_concurrent_jobs: int = 1
    runtime: dict = {}


class HeartbeatBody(BaseModel):
    device_id: str
    session_id: str
    status: str = "online"
    active_job_count: int = 0
    metrics: dict = {}


class NextJobBody(BaseModel):
    device_id: str
    session_id: str
    capabilities: list[str] = []


class StartBody(BaseModel):
    device_id: str
    session_id: str


class EvidenceAssetIn(BaseModel):
    asset_type: str
    asset_uri: str
    asset_hash: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    metadata: Optional[dict] = None


class ResultBody(BaseModel):
    device_id: str
    session_id: str
    model_id: Optional[str] = None
    result_type: str
    confidence: float = 0.0
    pass_fail_hint: str = "unknown"
    detections: list = []
    measurements: dict = {}
    features: dict = {}
    evidence_assets: list[EvidenceAssetIn] = []
    raw_output: dict = {}
    model_hash: Optional[str] = None


class FailBody(BaseModel):
    device_id: str
    session_id: str
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class CreateJobBody(BaseModel):
    tenant_id: str = "default"
    source_asset_id: Optional[str] = None
    inspection_id: Optional[str] = None
    requested_by: Optional[str] = None
    task_type: str
    priority: str = "normal"
    input_payload: dict = {}


class CaptureUploadBody(BaseModel):
    tenant_id: str = "default"
    device_id: str
    session_id: str
    user_id: Optional[str] = None
    captured_at: Optional[str] = None
    candidate_confidence: Optional[float] = None
    gps: dict = {}
    image_uri: str
    image_hash: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    task_type: str = "defect_candidate_detection"


# ── Device APIs (§12.1) ──────────────────────────────────────────────────────
@router.post("/api/edge-cv/devices/register", status_code=201)
def register_device(body: RegisterBody, db: Session = Depends(get_db_dep)):
    _require_enabled()
    device, session, token = device_service.register_device(
        db,
        tenant_id=body.tenant_id,
        device_name=body.device_name,
        device_type=body.device_type,
        serial_number=body.serial_number,
        mac_address=body.mac_address,
        agent_version=body.agent_version,
        capabilities=body.capabilities,
        max_concurrent_jobs=body.max_concurrent_jobs,
    )
    return {
        "device_id": device.id,
        "session_id": session.session_id,
        "auth_token": token,
        "heartbeat_interval_seconds": config.edge_cv_heartbeat_interval_seconds(),
        "job_poll_interval_seconds": config.edge_cv_job_poll_interval_seconds(),
        "recapture_cooldown_seconds": config.edge_cv_recapture_cooldown_seconds(),
        "status": device.status,
    }


@router.post("/api/edge-cv/devices/heartbeat")
def heartbeat(body: HeartbeatBody, claims: dict = Depends(require_device_token), db: Session = Depends(get_db_dep)):
    _assert_identity(claims, body.device_id, body.session_id)
    try:
        device = device_service.heartbeat(
            db,
            device_id=body.device_id,
            session_id=body.session_id,
            status=body.status,
            active_job_count=body.active_job_count,
            metrics=body.metrics,
        )
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="device_not_found")
    except InvalidSession:
        raise HTTPException(status_code=409, detail="stale_or_unknown_session")
    return {"device_id": device.id, "status": device.status, "next_heartbeat_seconds": config.edge_cv_heartbeat_interval_seconds()}


@router.get("/api/edge-cv/devices")
def list_devices(tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    _require_enabled()
    return [device_service.device_view(d) for d in device_service.list_devices(db, tenant_id)]


@router.get("/api/edge-cv/devices/{device_id}")
def read_device(device_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    _require_enabled()
    try:
        return device_service.device_view(device_service.get_device(db, device_id, tenant_id))
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="device_not_found")


@router.post("/api/edge-cv/devices/{device_id}/disable")
def disable_device(device_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    _require_enabled()
    try:
        return device_service.device_view(device_service.disable_device(db, device_id, tenant_id))
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="device_not_found")


@router.post("/api/edge-cv/devices/{device_id}/enable")
def enable_device(device_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    _require_enabled()
    try:
        return device_service.device_view(device_service.enable_device(db, device_id, tenant_id))
    except DeviceNotFound:
        raise HTTPException(status_code=404, detail="device_not_found")


# ── Edge-agent job APIs (§12.3) ──────────────────────────────────────────────
@router.post("/api/edge-cv/jobs/next")
def pull_next_job(body: NextJobBody, claims: dict = Depends(require_device_token), db: Session = Depends(get_db_dep)):
    _assert_identity(claims, body.device_id, body.session_id)
    try:
        job = dispatcher.lease_next_job_for_device(
            db, device_id=body.device_id, session_id=body.session_id, capabilities=body.capabilities
        )
    except InvalidJobState:
        raise HTTPException(status_code=409, detail="stale_or_unknown_session")
    if job is None:
        return {"job": None, "poll_after_seconds": config.edge_cv_job_poll_interval_seconds()}

    model = dispatcher.resolve_model_for_task(db, job.tenant_id, job.task_type)
    model_block = None
    if model is not None:
        model_block = {
            "model_id": model.id,
            "model_name": model.model_name,
            "model_version": model.model_version,
            "model_format": model.model_format,
            "artifact_uri": model.artifact_uri,
            "model_hash": model.model_hash,
        }
    return {
        "job": {
            "cv_job_id": job.id,
            "task_type": job.task_type,
            "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
            "model": model_block,
            "input_payload": job.input_payload_json or {},
        }
    }


@router.post("/api/edge-cv/jobs/{job_id}/start")
def start_job(job_id: str, body: StartBody, claims: dict = Depends(require_device_token), db: Session = Depends(get_db_dep)):
    _assert_identity(claims, body.device_id, body.session_id)
    try:
        job = dispatcher.mark_started(db, job_id=job_id, device_id=body.device_id, session_id=body.session_id)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="job_not_found")
    except InvalidJobState as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"cv_job_id": job.id, "status": job.status}


@router.post("/api/edge-cv/jobs/{job_id}/result", status_code=201)
def upload_result(job_id: str, body: ResultBody, claims: dict = Depends(require_device_token), db: Session = Depends(get_db_dep)):
    _assert_identity(claims, body.device_id, body.session_id)
    try:
        result = results.upload_result(
            db,
            job_id=job_id,
            device_id=body.device_id,
            session_id=body.session_id,
            model_id=body.model_id,
            result_type=body.result_type,
            confidence=body.confidence,
            pass_fail_hint=body.pass_fail_hint,
            detections=body.detections,
            measurements=body.measurements,
            features=body.features,
            raw_output=body.raw_output,
            evidence_assets=[a.model_dump() for a in body.evidence_assets],
            verify_model_hash=body.model_hash,
        )
    except ResultRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except ResultValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return results.result_view(db, result)


@router.post("/api/edge-cv/jobs/{job_id}/fail")
def fail_job(job_id: str, body: FailBody, claims: dict = Depends(require_device_token), db: Session = Depends(get_db_dep)):
    _assert_identity(claims, body.device_id, body.session_id)
    try:
        job = dispatcher.fail_job(
            db,
            job_id=job_id,
            device_id=body.device_id,
            session_id=body.session_id,
            error_code=body.error_code,
            error_message=body.error_message,
        )
    except JobNotFound:
        raise HTTPException(status_code=404, detail="job_not_found")
    except InvalidJobState as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"cv_job_id": job.id, "status": job.status, "retry_count": job.retry_count}


# ── Live-capture upload (addendum §4) ────────────────────────────────────────
@router.post("/api/edge-cv/captures/upload", status_code=201)
def upload_capture(body: CaptureUploadBody, claims: dict = Depends(require_device_token), db: Session = Depends(get_db_dep)):
    _assert_identity(claims, body.device_id, body.session_id)
    captured_at = None
    if body.captured_at:
        from datetime import datetime

        try:
            captured_at = datetime.fromisoformat(body.captured_at)
        except ValueError:
            raise HTTPException(status_code=422, detail="invalid captured_at (expected ISO 8601)")
    try:
        capture, cv_job_id = captures.ingest_capture(
            db,
            tenant_id=body.tenant_id,
            device_id=body.device_id,
            session_id=body.session_id,
            user_id=body.user_id,
            captured_at=captured_at,
            candidate_confidence=body.candidate_confidence,
            gps=body.gps,
            image_uri=body.image_uri,
            image_hash=body.image_hash,
            width=body.width,
            height=body.height,
            task_type=body.task_type,
        )
    except CaptureRejected as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {
        "capture_id": capture.id,
        "cv_job_id": cv_job_id,
        "qc_model_dispatch_status": capture.qc_model_dispatch_status,
        "capture_time_label": capture.capture_time_label,
    }


# ── Operator/admin CV job APIs (§12.2) ───────────────────────────────────────
@router.post("/api/cv/jobs", status_code=201)
def create_cv_job(body: CreateJobBody, db: Session = Depends(get_db_dep)):
    _require_enabled()
    try:
        job = dispatcher.create_job(
            db,
            tenant_id=body.tenant_id,
            task_type=body.task_type,
            source_asset_id=body.source_asset_id,
            inspection_id=body.inspection_id,
            requested_by=body.requested_by,
            priority=body.priority,
            input_payload=body.input_payload,
        )
    except InvalidJobState as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return dispatcher.job_view(db, job)


@router.get("/api/cv/jobs/{job_id}")
def read_cv_job(job_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    _require_enabled()
    from src.db.edge_cv_models import CVJob

    job = db.get(CVJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="job_not_found")
    return dispatcher.job_view(db, job)


@router.post("/api/cv/jobs/{job_id}/cancel")
def cancel_cv_job(job_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    _require_enabled()
    try:
        job = dispatcher.cancel_job(db, job_id, tenant_id)
    except JobNotFound:
        raise HTTPException(status_code=404, detail="job_not_found")
    except InvalidJobState as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return dispatcher.job_view(db, job)
