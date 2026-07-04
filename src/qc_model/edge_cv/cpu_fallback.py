"""Service-side CPU fallback runner (§15).

When no capable edge device is online, the CPU fallback keeps the QC workflow
moving instead of freezing. It does *not* perform advanced CV in this iteration:
it produces a structured, low-confidence, ``needs_human_review`` result so a
human still adjudicates. It exists to prove the workflow is never blocked by a
missing/offline Jetson (§5.4).

The fallback processes a job entirely server-side: it ensures a ``cpu_runner``
device row exists, transitions the job queued -> running -> completed, and
persists the result + evidence asset via the normal result path — so a CPU
result is audited exactly like an edge-device result.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from src import config
from src.db.models import _utcnow
from src.db.edge_cv_models import CVJob, CVResult, CVResultAsset, EdgeCVDevice
from src.qc_model.edge_cv import constants as C
from src.qc_model.edge_cv.dispatcher import _transition, record_event
from src.qc_model.edge_cv.mock_cv import mock_infer

_CPU_DEVICE_NAME = "cpu-fallback-runner"


def _uid(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex}"


def ensure_cpu_device(db: Session, tenant_id: str = "default") -> EdgeCVDevice:
    """Return the tenant's CPU fallback device row, creating it if needed."""
    device = (
        db.query(EdgeCVDevice)
        .filter_by(tenant_id=tenant_id, device_name=_CPU_DEVICE_NAME)
        .first()
    )
    if device is not None:
        return device
    device = EdgeCVDevice(
        id=_uid("edge_dev_"),
        tenant_id=tenant_id,
        device_name=_CPU_DEVICE_NAME,
        device_type=C.DEVICE_TYPE_CPU_RUNNER,
        status=C.DEVICE_ONLINE,
        capabilities_json=[
            "image_preprocess",
            "object_detection",
            "defect_candidate_detection",
            "counting",
            "feature_extraction",
            "color_check",
            "alignment_check",
            "ocr_optional",
        ],
        max_concurrent_jobs=4,
        current_active_jobs=0,
        last_heartbeat_at=_utcnow(),
        last_seen_at=_utcnow(),
        is_enabled=True,
    )
    db.add(device)
    db.flush()
    return device


def run_cpu_fallback(db: Session, job: CVJob) -> CVResult:
    """Process a queued job on the CPU fallback runner (§15, §24.1).

    Marks the job leased -> running -> completed and persists a structured
    ``needs_human_review`` result. Returns the created result.
    """
    if not config.edge_cv_cpu_fallback():
        raise RuntimeError("CPU fallback is disabled (EDGE_CV_CPU_FALLBACK=false)")

    device = ensure_cpu_device(db, job.tenant_id)
    now = _utcnow()

    # queued -> leased -> running (server-side, short synthetic lease for audit).
    job.assigned_device_id = device.id
    job.lease_owner_device_id = device.id
    job.lease_owner_session_id = None
    job.lease_expires_at = now + timedelta(seconds=config.edge_cv_job_lease_seconds())
    job.leased_at = now
    _transition(db, job, C.JOB_LEASED, event_type="cpu_fallback_leased", created_by="cpu_runner")
    job.started_at = _utcnow()
    _transition(db, job, C.JOB_RUNNING, event_type="cpu_fallback_started", created_by="cpu_runner")

    inference = mock_infer(job.task_type, job.input_payload_json, runner="cpu_fallback")

    _transition(db, job, C.JOB_UPLOADING, event_type="uploading_result", created_by="cpu_runner")

    result = CVResult(
        id=_uid("cv_result_"),
        tenant_id=job.tenant_id,
        cv_job_id=job.id,
        device_id=device.id,
        session_id=None,
        model_id=job.model_id,
        result_type=inference["result_type"],
        # CPU fallback is deliberately lower-confidence than an edge result.
        confidence=min(0.5, float(inference.get("confidence", 0.5))),
        pass_fail_hint="needs_human_review",
        detections_json=inference.get("detections", []),
        measurements_json=inference.get("measurements", {}),
        features_json=inference.get("features", {}),
        raw_output_json={**inference.get("raw_output", {}), "fallback": True},
    )
    db.add(result)
    db.flush()
    for asset in inference.get("evidence_assets", []):
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
            )
        )

    job.completed_at = _utcnow()
    job.lease_expires_at = None
    job.lease_owner_device_id = None
    _transition(db, job, C.JOB_COMPLETED, event_type="cpu_fallback_completed", created_by="cpu_runner")
    record_event(
        db, job, from_status=C.JOB_COMPLETED, to_status=C.JOB_COMPLETED,
        event_type="fallback", payload={"runner": "cpu_fallback"}, created_by="cpu_runner",
    )
    db.commit()
    db.refresh(result)
    return result
