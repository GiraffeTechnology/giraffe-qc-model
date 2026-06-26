"""Pad QC E2E API routes.

These routes connect the existing Pad UI/session layer to the PR10 inspection
execution services. They keep model output and final verdicts behind the QC
service layer instead of trusting chat output directly.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.db.execution_models import (
    QCCheckpointResult,
    QCIncidentalFinding,
    QCInspectionJob,
    QCInspectionMedia,
)
from src.db.sku_models import QCSkuItem
from src.inspection.api_service import (
    attach_inspection_media,
    finalize_inspection_job,
    get_inspection_report,
    ingest_model_output,
)
from src.pad.model_adapter import DeterministicPadQCAdapter

router = APIRouter(prefix="/api/v1/pad", tags=["pad-qc-e2e"])


def _require_operator(request: Request) -> Optional[int]:
    operator_id = request.session.get("operator_id")
    if not operator_id:
        return None
    return int(operator_id)


def _tenant_id(request: Request) -> str:
    return request.session.get("tenant_id", "demo")


@router.get("/skus")
async def search_skus(
    request: Request,
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db_dep),
):
    """Search active SKU catalog entries for the Pad selector."""
    if _require_operator(request) is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    query = db.query(QCSkuItem).filter_by(tenant_id=_tenant_id(request), status="active")
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(
            QCSkuItem.item_number.ilike(pattern),
            QCSkuItem.name.ilike(pattern),
            QCSkuItem.category.ilike(pattern),
        ))
    skus = query.order_by(QCSkuItem.item_number.asc()).limit(limit).all()
    return JSONResponse({
        "skus": [
            {
                "id": sku.id,
                "item_number": sku.item_number,
                "name": sku.name,
                "category": sku.category,
                "status": sku.status,
            }
            for sku in skus
        ]
    })


@router.post("/inspections/{job_id}/media")
async def attach_pad_inspection_media(
    request: Request,
    job_id: str,
    image: UploadFile = File(...),
    angle: Optional[str] = Form(default=None),
    view_type: Optional[str] = Form(default="inspection"),
    db: Session = Depends(get_db_dep),
):
    """Attach an uploaded Pad image to a concrete inspection job."""
    if _require_operator(request) is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = _tenant_id(request)

    job = db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)

    content = await image.read()
    if not content:
        return JSONResponse({"error": "empty image upload"}, status_code=400)

    digest = hashlib.sha256(content).hexdigest()
    safe_name = os.path.basename(image.filename or "inspection-image.bin").replace("/", "_")
    media_dir = os.path.join(tempfile.gettempdir(), "giraffe_qc_pad_media", job_id)
    os.makedirs(media_dir, exist_ok=True)
    local_path = os.path.join(media_dir, f"{digest[:12]}_{safe_name}")
    with open(local_path, "wb") as fh:
        fh.write(content)

    media = attach_inspection_media(
        db,
        job_id=job_id,
        local_path=local_path,
        angle=angle,
        view_type=view_type,
        sha256=digest,
        mime_type=image.content_type,
        tenant_id=tenant_id,
    )
    return JSONResponse({
        "status": "media_attached",
        "media_id": media.id,
        "job_id": job_id,
        "filename": image.filename,
        "size_bytes": len(content),
        "sha256": digest,
        "local_path": local_path,
    }, status_code=201)


@router.post("/inspections/{job_id}/run_model")
async def run_pad_model(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    """Run the deterministic Pad adapter and ingest output through QC services."""
    if _require_operator(request) is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = _tenant_id(request)

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        body = {}

    job = db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)

    media_id = body.get("media_id")
    media = None
    if media_id:
        media = db.query(QCInspectionMedia).filter_by(id=media_id, job_id=job_id, tenant_id=tenant_id).first()
        if media is None:
            return JSONResponse({"error": "media not found for this job"}, status_code=404)
    else:
        media = (
            db.query(QCInspectionMedia)
            .filter_by(job_id=job_id, tenant_id=tenant_id)
            .order_by(QCInspectionMedia.created_at.desc())
            .first()
        )

    adapter_result = DeterministicPadQCAdapter().run(db, job_id=job_id, media=media, options=body)
    try:
        model_result = ingest_model_output(
            db,
            job_id=job_id,
            provider=adapter_result.provider,
            model_name=adapter_result.model_name,
            raw_output=adapter_result.raw_output,
            media_id=media.id if media else None,
            http_status=200,
            elapsed_ms=adapter_result.elapsed_ms,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    checkpoint_rows = db.query(QCCheckpointResult).filter_by(job_id=job_id).all()
    return JSONResponse({
        "status": "model_output_ingested",
        "job_id": job_id,
        "media_id": media.id if media else None,
        "model_result_id": model_result.id,
        "checkpoint_results": [
            {
                "point_code": row.detection_point.point_code,
                "label": row.detection_point.label,
                "result": row.result,
                "observed_value": row.observed_value,
                "confidence": row.confidence,
                "notes": row.notes,
            }
            for row in checkpoint_rows
        ],
    }, status_code=201)


@router.post("/inspections/{job_id}/finalize")
async def finalize_pad_inspection(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    """Finalize a Pad inspection job using the authoritative QC verdict service."""
    if _require_operator(request) is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = _tenant_id(request)

    job = db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)
    try:
        report = finalize_inspection_job(db, job_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "status": "finalized",
        "job_id": job_id,
        "overall_result": report.overall_result,
        "report_id": report.id,
        "checkpoint_results_count": report.checkpoint_results_count,
        "findings_count": report.findings_count,
        "report_url": f"/pad/inspections/{job_id}/report",
    })


@router.get("/inspections/{job_id}/report")
async def pad_report_json(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    """Return a detailed Pad report card JSON for tablet rendering."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = _tenant_id(request)

    job = db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)
    try:
        report = get_inspection_report(db, job_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    checkpoint_rows = db.query(QCCheckpointResult).filter_by(job_id=job_id).all()
    finding_rows = db.query(QCIncidentalFinding).filter_by(job_id=job_id).all()
    return JSONResponse({
        "job": {
            "id": job.id,
            "sku_id": job.sku_id,
            "tenant_id": job.tenant_id,
            "active_standard_revision_id": job.active_standard_revision_id,
            "status": job.status,
        },
        "report": {
            "id": report.id,
            "overall_result": report.overall_result,
            "summary_text": report.summary_text,
            "checkpoint_results_count": report.checkpoint_results_count,
            "findings_count": report.findings_count,
        },
        "checkpoint_results": [
            {
                "point_code": row.detection_point.point_code,
                "label": row.detection_point.label,
                "expected_value": row.detection_point.expected_value,
                "result": row.result,
                "observed_value": row.observed_value,
                "confidence": row.confidence,
                "notes": row.notes,
            }
            for row in checkpoint_rows
        ],
        "incidental_findings": [
            {
                "severity": row.severity,
                "description": row.description,
                "location_hint": row.location_hint,
                "evidence_json": row.evidence_json,
            }
            for row in finding_rows
        ],
        "audit": {
            "operator_id": operator_id,
            "tenant_id": tenant_id,
            "job_id": job_id,
        },
    })
