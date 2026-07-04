"""CV result ingestion — validation, idempotent persistence, job completion.

The service validates every result before persistence (§17.3) and is idempotent
(§17.4): a duplicate upload from the same device+session for the same job
returns the existing result rather than creating a second one.

Two failure shapes are distinguished:

* :class:`ResultRejected` — an *authorization* failure (unknown job, wrong
  device/session, expired lease). Current job state is **never** mutated, so a
  stale session can never corrupt a job that has already moved on (§8.4).
* :class:`ResultValidationError` — a *payload* failure (bad schema, missing
  fields, unknown asset/hint). QC must not silently pass on bad evidence, so the
  job is moved to ``manual_review_required`` and an event is written.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import _utcnow
from src.db.edge_cv_models import CVJob, CVResult, CVResultAsset, EdgeCVModel
from src.qc_model.edge_cv import constants as C
from src.qc_model.edge_cv.dispatcher import _release_device_slot, _transition
from src.qc_model.edge_cv.service import _active_session, as_aware_utc


class ResultRejected(Exception):
    """Authorization failure — job state is left untouched."""


class ResultValidationError(Exception):
    """Payload failure — job is escalated to manual review."""


def _uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def _result_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def upload_result(
    db: Session,
    *,
    job_id: str,
    device_id: str,
    session_id: str,
    model_id: Optional[str] = None,
    result_type: str,
    confidence: float = 0.0,
    pass_fail_hint: str = "unknown",
    detections: Optional[list] = None,
    measurements: Optional[dict] = None,
    features: Optional[dict] = None,
    raw_output: Optional[dict] = None,
    evidence_assets: Optional[list[dict]] = None,
    verify_model_hash: Optional[str] = None,
) -> CVResult:
    """Validate + persist a CV result and complete the job (§12.3, §10, §17).

    Raises :class:`ResultRejected` for auth failures (no state change) and
    :class:`ResultValidationError` for payload failures (job → manual review).
    """
    job = db.get(CVJob, job_id)
    if job is None:
        raise ResultRejected("unknown_job")

    # ── Authorization: lease ownership + session freshness (never mutate) ────
    if job.lease_owner_device_id != device_id:
        raise ResultRejected("wrong_device")
    if job.lease_owner_session_id != session_id:
        raise ResultRejected("stale_or_wrong_session")
    # The uploading session must still be active — a session superseded by a
    # reconnect (§8.4) can never persist a result over current state (Cycle 5).
    if _active_session(db, device_id, session_id) is None:
        raise ResultRejected("stale_or_wrong_session")
    if job.status in C.JOB_TERMINAL_STATES and job.status != C.JOB_COMPLETED:
        raise ResultRejected(f"job_not_accepting_results:{job.status}")
    lease_exp = as_aware_utc(job.lease_expires_at)
    if lease_exp is not None and lease_exp < _utcnow() and job.status != C.JOB_COMPLETED:
        raise ResultRejected("lease_expired")

    # ── Idempotency: one result per (job, device, session) (§17.4) ───────────
    existing = (
        db.query(CVResult)
        .filter_by(cv_job_id=job.id, device_id=device_id, session_id=session_id)
        .first()
    )
    if existing is not None:
        return existing

    # ── Optional model-hash check (§17.3) ────────────────────────────────────
    if verify_model_hash is not None and job.model_id:
        model = db.get(EdgeCVModel, job.model_id)
        if model is not None and model.model_hash and model.model_hash != verify_model_hash:
            job.error_code = "model_hash_mismatch"
            job.error_message = "uploaded result model hash does not match job model"
            _fail_to_manual_review(db, job, "model_hash_mismatch")
            db.commit()
            raise ResultValidationError("model_hash_mismatch")

    # ── Payload schema validation (§17.3) ────────────────────────────────────
    error = _validate_payload(result_type, pass_fail_hint, evidence_assets)
    if error is not None:
        job.error_code = "invalid_result_schema"
        job.error_message = error
        _fail_to_manual_review(db, job, error)
        db.commit()
        raise ResultValidationError(error)

    # ── running -> uploading_result -> completed ─────────────────────────────
    if job.status in (C.JOB_LEASED, C.JOB_RUNNING):
        _transition(db, job, C.JOB_UPLOADING, event_type="uploading_result", created_by=device_id)

    payload_for_hash = {
        "job_id": job.id,
        "result_type": result_type,
        "confidence": confidence,
        "pass_fail_hint": pass_fail_hint,
        "detections": detections or [],
        "measurements": measurements or {},
        "features": features or {},
    }
    result = CVResult(
        id=_uid("cv_result_"),
        tenant_id=job.tenant_id,
        cv_job_id=job.id,
        device_id=device_id,
        session_id=session_id,
        model_id=model_id or job.model_id,
        result_type=result_type,
        confidence=float(confidence or 0.0),
        pass_fail_hint=pass_fail_hint,
        detections_json=detections or [],
        measurements_json=measurements or {},
        features_json=features or {},
        raw_output_json=raw_output or {},
        result_hash=_result_hash(payload_for_hash),
    )
    db.add(result)
    db.flush()

    for asset in evidence_assets or []:
        db.add(
            CVResultAsset(
                id=_uid("cv_asset_"),
                tenant_id=job.tenant_id,
                cv_result_id=result.id,
                asset_type=asset["asset_type"],
                asset_uri=asset["asset_uri"],
                asset_hash=asset.get("asset_hash"),
                width=asset.get("width"),
                height=asset.get("height"),
                metadata_json=asset.get("metadata"),
            )
        )

    _release_device_slot(db, job.lease_owner_device_id)
    job.completed_at = _utcnow()
    job.lease_expires_at = None
    _transition(db, job, C.JOB_COMPLETED, event_type="completed", created_by=device_id)
    db.commit()
    db.refresh(result)
    return result


def _validate_payload(
    result_type: str, pass_fail_hint: str, evidence_assets: Optional[list[dict]]
) -> Optional[str]:
    """Return an error string for an invalid payload, or None if valid."""
    if not result_type or not isinstance(result_type, str):
        return "missing_or_invalid_result_type"
    if pass_fail_hint not in C.PASS_FAIL_HINTS:
        return f"invalid_pass_fail_hint:{pass_fail_hint}"
    for asset in evidence_assets or []:
        if not isinstance(asset, dict):
            return "invalid_asset_entry"
        if asset.get("asset_type") not in C.ASSET_TYPES:
            return f"unknown_asset_type:{asset.get('asset_type')}"
        if not asset.get("asset_uri"):
            return "asset_missing_uri"
    return None


def _fail_to_manual_review(db: Session, job: CVJob, reason: str) -> None:
    _release_device_slot(db, job.lease_owner_device_id)
    job.lease_owner_device_id = None
    job.lease_owner_session_id = None
    job.lease_expires_at = None
    _transition(
        db,
        job,
        C.JOB_MANUAL_REVIEW,
        event_type="result_rejected",
        payload={"reason": reason},
    )


def result_view(db: Session, result: CVResult) -> dict:
    return {
        "result_id": result.id,
        "cv_job_id": result.cv_job_id,
        "device_id": result.device_id,
        "session_id": result.session_id,
        "model_id": result.model_id,
        "result_type": result.result_type,
        "confidence": result.confidence,
        "pass_fail_hint": result.pass_fail_hint,
        "detections": result.detections_json or [],
        "measurements": result.measurements_json or {},
        "features": result.features_json or {},
        "raw_output": result.raw_output_json or {},
        "result_hash": result.result_hash,
        "assets": [
            {
                "asset_id": a.id,
                "asset_type": a.asset_type,
                "asset_uri": a.asset_uri,
                "asset_hash": a.asset_hash,
                "width": a.width,
                "height": a.height,
            }
            for a in result.assets
        ],
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }
