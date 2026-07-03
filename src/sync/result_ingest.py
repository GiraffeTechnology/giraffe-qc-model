"""Idempotent reverse-sync: Pad → Server inspection-job batch upload (Task 03).

Completed inspection jobs queued in the Pad outbox are uploaded in batches during
a sync window. Built entirely on the generation-3 execution tables
(``qc_inspection_jobs`` + checkpoint results + media + final report). The legacy
generation-2 ``sync_targets``/``sync_jobs`` tables are NOT used.

Idempotency: the Pad supplies a client-generated job UUID as the job id. Re-upload
of the same UUID is a no-op ("duplicate") — the server never creates a second job.
Each job in a batch is processed independently so a partial/resumed upload makes
forward progress.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from src.db.execution_models import (
    QCCheckpointResult,
    QCFinalReport,
    QCInspectionJob,
    QCInspectionMedia,
)
from src.db.sku_models import QCDetectionPoint, QCSkuItem, QCSkuStandardRevision

# Pad per-point verdicts → gen-3 checkpoint result vocabulary. review_required
# maps to low_confidence, which by policy cannot contribute to a pass.
_CHECKPOINT_MAP = {
    "pass": "pass",
    "fail": "fail",
    "review_required": "low_confidence",
    "low_confidence": "low_confidence",
    "not_visible": "not_visible",
    "missing": "missing",
}
_OVERALL_MAP = {
    "pass": "pass",
    "fail": "fail",
    "review_required": "review_required",
    "accepted": "pass",
    "not_accepted": "fail",
}


def _uid() -> str:
    import uuid
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class JobIngestResult:
    job_uuid: str
    status: str          # "created" | "duplicate" | "rejected"
    reason: Optional[str] = None


class JobIngestError(ValueError):
    """A single job in the batch is invalid (validated before any write)."""


def ingest_job_batch(
    db: Session, tenant_id: str, jobs: list[dict[str, Any]],
) -> list[JobIngestResult]:
    """Ingest a batch of completed Pad jobs idempotently. Returns per-job status.

    Each job dict:
      job_uuid, sku_id, active_standard_revision_id, overall_result,
      job_ref?, created_by?, notes?, started_at?, completed_at?,
      checkpoint_results: [{detection_point_id, result, observed_value?, confidence?, notes?}],
      media: [{local_path?, image_url?, sha256?, angle?, view_type?, width_px?, height_px?, mime_type?}]
    """
    results: list[JobIngestResult] = []
    for job in jobs:
        job_uuid = str(job.get("job_uuid") or "").strip()
        if not job_uuid:
            results.append(JobIngestResult("", "rejected", "missing job_uuid"))
            continue
        try:
            outcome = _ingest_one(db, tenant_id, job_uuid, job)
            results.append(outcome)
        except JobIngestError as exc:
            db.rollback()
            results.append(JobIngestResult(job_uuid, "rejected", str(exc)))
    return results


def _ingest_one(db: Session, tenant_id: str, job_uuid: str, job: dict[str, Any]) -> JobIngestResult:
    # Idempotency: same job UUID for this tenant → dedupe, never a second job.
    existing = db.query(QCInspectionJob).filter_by(id=job_uuid, tenant_id=tenant_id).first()
    if existing is not None:
        return JobIngestResult(job_uuid, "duplicate")

    sku_id = str(job.get("sku_id") or "")
    revision_id = str(job.get("active_standard_revision_id") or "")
    overall_raw = str(job.get("overall_result") or "").lower()

    sku = db.query(QCSkuItem).filter_by(id=sku_id, tenant_id=tenant_id).first()
    if sku is None:
        raise JobIngestError(f"unknown sku_id {sku_id!r} for tenant")
    revision = db.query(QCSkuStandardRevision).filter_by(
        id=revision_id, tenant_id=tenant_id, sku_id=sku_id,
    ).first()
    if revision is None:
        raise JobIngestError(f"unknown standard revision {revision_id!r} for sku {sku_id!r}")
    if overall_raw not in _OVERALL_MAP:
        raise JobIngestError(f"invalid overall_result {overall_raw!r}")
    overall = _OVERALL_MAP[overall_raw]

    checkpoints = job.get("checkpoint_results") or []
    media_items = job.get("media") or []

    # Validate all checkpoints BEFORE any write.
    valid_point_ids = {
        p.id for p in db.query(QCDetectionPoint.id)
        .filter(QCDetectionPoint.standard_revision_id == revision_id)
        .all()
    }
    seen_points: set[str] = set()
    prepared_cp: list[dict[str, Any]] = []
    for cp in checkpoints:
        dp_id = str(cp.get("detection_point_id") or "")
        if dp_id not in valid_point_ids:
            raise JobIngestError(f"checkpoint references unknown detection_point_id {dp_id!r}")
        if dp_id in seen_points:
            raise JobIngestError(f"duplicate detection_point_id {dp_id!r} in job")
        seen_points.add(dp_id)
        result_raw = str(cp.get("result") or "").lower()
        if result_raw not in _CHECKPOINT_MAP:
            raise JobIngestError(f"invalid checkpoint result {result_raw!r}")
        prepared_cp.append({
            "detection_point_id": dp_id,
            "result": _CHECKPOINT_MAP[result_raw],
            "observed_value": cp.get("observed_value"),
            "confidence": float(cp.get("confidence", 1.0)),
            "notes": cp.get("notes"),
        })

    # Persist (single job unit; batch caller commits nothing partial per job).
    inspection = QCInspectionJob(
        id=job_uuid,
        tenant_id=tenant_id,
        sku_id=sku_id,
        active_standard_revision_id=revision_id,
        job_ref=job.get("job_ref"),
        status=overall,
        created_by=job.get("created_by"),
        notes=job.get("notes"),
        started_at=_parse_dt(job.get("started_at")),
        completed_at=_parse_dt(job.get("completed_at")) or _now(),
    )
    db.add(inspection)

    for cp in prepared_cp:
        db.add(QCCheckpointResult(
            id=_uid(),
            job_id=job_uuid,
            tenant_id=tenant_id,
            detection_point_id=cp["detection_point_id"],
            result=cp["result"],
            observed_value=cp["observed_value"],
            confidence=cp["confidence"],
            notes=cp["notes"],
        ))

    for m in media_items:
        db.add(QCInspectionMedia(
            id=_uid(),
            job_id=job_uuid,
            tenant_id=tenant_id,
            image_url=m.get("image_url"),
            local_path=m.get("local_path"),
            angle=m.get("angle"),
            view_type=m.get("view_type"),
            sha256=m.get("sha256"),
            width_px=m.get("width_px"),
            height_px=m.get("height_px"),
            mime_type=m.get("mime_type"),
        ))

    db.add(QCFinalReport(
        id=_uid(),
        job_id=job_uuid,
        tenant_id=tenant_id,
        overall_result=overall,
        summary_text=job.get("notes") or f"Uploaded from Pad outbox ({overall})",
        checkpoint_results_count=len(prepared_cp),
        findings_count=0,
        generated_at=_now(),
    ))
    db.commit()
    return JobIngestResult(job_uuid, "created")
