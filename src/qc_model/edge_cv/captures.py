"""Live-capture ingestion → qc-model handoff (Live-Capture Auto-Lock addendum).

An edge device runs the lock/capture logic locally (device-side capture state
machine: watching → candidate_detected → locking → locked → captured →
uploading). Only the final still frame + metadata crosses the API boundary here.

On receipt the service:
  1. validates device/session identity (§5.2);
  2. derives ``capture_time_label`` (mmdd_hhmmss) from the canonical
     ``captured_at``;
  3. persists a ``cv_captured_photos`` row (always — even if dispatch fails);
  4. auto-creates a ``cv_job`` (same dispatcher path) with ``source_asset_id`` =
     the capture image, links it, and marks ``qc_model_dispatch_status``.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from src.db.models import _utcnow
from src.db.edge_cv_models import CVCapturedPhoto
from src.qc_model.edge_cv import dispatcher
from src.qc_model.edge_cv.service import _active_session


class CaptureRejected(Exception):
    """Device/session identity check failed — nothing is persisted."""


def _uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def capture_time_label(captured_at: datetime) -> str:
    """Derive the mmdd_hhmmss display/filename label (not a canonical time)."""
    return captured_at.strftime("%m%d_%H%M%S")


def ingest_capture(
    db: Session,
    *,
    tenant_id: str = "default",
    device_id: str,
    session_id: str,
    user_id: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    candidate_confidence: Optional[float] = None,
    gps: Optional[dict] = None,
    image_uri: str,
    image_hash: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    task_type: str = "defect_candidate_detection",
    trigger_type: str = "live_auto_lock",
) -> tuple[CVCapturedPhoto, Optional[str]]:
    """Persist a capture and auto-create its qc-model job.

    Returns ``(capture_row, cv_job_id)`` — ``cv_job_id`` is ``None`` when job
    creation failed (the capture is still persisted with
    ``qc_model_dispatch_status='failed'`` so it can be re-dispatched later).
    """
    session = _active_session(db, device_id, session_id)
    if session is None:
        raise CaptureRejected("stale_or_unknown_session")

    when = captured_at or _utcnow()
    gps = gps or {}
    capture = CVCapturedPhoto(
        id=_uid("cv_capture_"),
        tenant_id=tenant_id,
        device_id=device_id,
        session_id=session_id,
        captured_by_user_id=user_id,
        trigger_type=trigger_type,
        candidate_confidence=candidate_confidence,
        captured_at=when,
        capture_time_label=capture_time_label(when),
        gps_lat=gps.get("lat"),
        gps_lon=gps.get("lon"),
        gps_accuracy_m=gps.get("accuracy_m"),
        image_uri=image_uri,
        image_hash=image_hash,
        width=width,
        height=height,
        qc_model_dispatch_status="pending",
    )
    db.add(capture)
    db.commit()
    db.refresh(capture)

    # Auto-create the downstream qc-model job (same dispatcher path).
    cv_job_id: Optional[str] = None
    try:
        job = dispatcher.create_job(
            db,
            tenant_id=tenant_id,
            task_type=task_type,
            source_asset_id=capture.image_uri,
            requested_by=user_id,
            input_payload={
                "image_uri": capture.image_uri,
                "capture_id": capture.id,
                "candidate_confidence": candidate_confidence,
            },
        )
        cv_job_id = job.id
        capture.linked_cv_job_id = job.id
        capture.qc_model_dispatch_status = "dispatched"
    except Exception:  # never lose the photo if downstream dispatch fails
        capture.qc_model_dispatch_status = "failed"
    db.commit()
    db.refresh(capture)
    return capture, cv_job_id


def capture_view(capture: CVCapturedPhoto) -> dict:
    return {
        "capture_id": capture.id,
        "tenant_id": capture.tenant_id,
        "device_id": capture.device_id,
        "session_id": capture.session_id,
        "user_id": capture.captured_by_user_id,
        "trigger_type": capture.trigger_type,
        "candidate_confidence": capture.candidate_confidence,
        "captured_at": capture.captured_at.isoformat() if capture.captured_at else None,
        "capture_time_label": capture.capture_time_label,
        "gps": {
            "lat": capture.gps_lat,
            "lon": capture.gps_lon,
            "accuracy_m": capture.gps_accuracy_m,
        },
        "image_uri": capture.image_uri,
        "image_hash": capture.image_hash,
        "width": capture.width,
        "height": capture.height,
        "linked_cv_job_id": capture.linked_cv_job_id,
        "qc_model_dispatch_status": capture.qc_model_dispatch_status,
        "created_at": capture.created_at.isoformat() if capture.created_at else None,
    }
