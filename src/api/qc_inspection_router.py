"""FastAPI router for QC inspection job execution."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth import Principal, require_principal
from src.api.deps import get_db_dep
from src.inspection.api_service import (
    attach_inspection_media,
    create_inspection_job_from_api,
    finalize_inspection_job,
    get_inspection_report,
    ingest_model_output,
)

router = APIRouter(
    prefix="/api/v1/qc/inspection-jobs",
    tags=["qc-inspection"],
    dependencies=[Depends(require_principal)],
)


def _get_job_or_404(db: Session, job_id: str, tenant_id: str):
    from src.db.execution_models import QCInspectionJob

    job = db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Inspection job not found")
    return job


# ── Request / Response schemas ────────────────────────────────────────────────


class CreateJobRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    sku_id: str
    job_ref: Optional[str] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None


class AttachMediaRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    image_url: Optional[str] = None
    local_path: Optional[str] = None
    angle: Optional[str] = None
    view_type: Optional[str] = None
    sha256: Optional[str] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    mime_type: Optional[str] = None


class CheckpointResultInput(BaseModel):
    point_code: str
    result: str
    observed_value: Optional[str] = None
    confidence: float = 1.0
    notes: Optional[str] = None


class IncidentalFindingInput(BaseModel):
    severity: str = "minor"
    description: str
    location_hint: Optional[str] = None
    evidence_json: Optional[Dict[str, Any]] = None


class ModelOutputRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    provider: str
    model_name: str
    raw_output: Dict[str, Any]
    media_id: Optional[str] = None
    http_status: Optional[int] = None
    elapsed_ms: Optional[int] = None


class SubmitCheckpointRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    detection_point_id: str
    result: str
    observed_value: Optional[str] = None
    confidence: float = 1.0
    notes: Optional[str] = None


class SubmitFindingRequest(BaseModel):
    tenant_id: str = Field(min_length=1)
    description: str
    severity: str = "minor"
    location_hint: Optional[str] = None
    evidence_json: Optional[Dict[str, Any]] = None


class JobResponse(BaseModel):
    id: str
    tenant_id: str
    sku_id: str
    active_standard_revision_id: str
    job_ref: Optional[str]
    status: str
    created_by: Optional[str]


class ReportResponse(BaseModel):
    id: str
    job_id: str
    overall_result: str
    checkpoint_results_count: int
    findings_count: int
    summary_text: Optional[str]


class TenantRequest(BaseModel):
    tenant_id: str = Field(min_length=1)


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", status_code=201)
def create_job(
    body: CreateJobRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> JobResponse:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    try:
        job = create_inspection_job_from_api(
            db,
            sku_id=body.sku_id,
            tenant_id=body.tenant_id,
            job_ref=body.job_ref,
            created_by=body.created_by,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JobResponse(
        id=job.id,
        tenant_id=job.tenant_id,
        sku_id=job.sku_id,
        active_standard_revision_id=job.active_standard_revision_id,
        job_ref=job.job_ref,
        status=job.status,
        created_by=job.created_by,
    )


@router.get("/{job_id}")
def get_job(
    job_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> JobResponse:
    tenant_id = principal.tenant_id
    job = _get_job_or_404(db, job_id, tenant_id)
    return JobResponse(
        id=job.id,
        tenant_id=job.tenant_id,
        sku_id=job.sku_id,
        active_standard_revision_id=job.active_standard_revision_id,
        job_ref=job.job_ref,
        status=job.status,
        created_by=job.created_by,
    )


@router.post("/{job_id}/media", status_code=201)
def add_job_media(
    job_id: str,
    body: AttachMediaRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> dict:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    _get_job_or_404(db, job_id, body.tenant_id)
    try:
        media = attach_inspection_media(
            db,
            job_id=job_id,
            image_url=body.image_url,
            local_path=body.local_path,
            angle=body.angle,
            view_type=body.view_type,
            sha256=body.sha256,
            width_px=body.width_px,
            height_px=body.height_px,
            mime_type=body.mime_type,
            tenant_id=body.tenant_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"id": media.id, "job_id": job_id}


@router.post("/{job_id}/model-results", status_code=201)
def ingest_model_results(
    job_id: str,
    body: ModelOutputRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> dict:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    _get_job_or_404(db, job_id, body.tenant_id)
    try:
        model_result = ingest_model_output(
            db,
            job_id=job_id,
            provider=body.provider,
            model_name=body.model_name,
            raw_output=body.raw_output,
            media_id=body.media_id,
            http_status=body.http_status,
            elapsed_ms=body.elapsed_ms,
            tenant_id=body.tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": model_result.id, "job_id": job_id}


@router.post("/{job_id}/checkpoint-results", status_code=201)
def submit_checkpoint(
    job_id: str,
    body: SubmitCheckpointRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> dict:
    from src.inspection.service import submit_checkpoint_result
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    _get_job_or_404(db, job_id, body.tenant_id)
    try:
        cr = submit_checkpoint_result(
            db,
            job_id=job_id,
            detection_point_id=body.detection_point_id,
            result=body.result,
            observed_value=body.observed_value,
            confidence=body.confidence,
            notes=body.notes,
            tenant_id=body.tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": cr.id, "job_id": job_id, "result": cr.result}


@router.post("/{job_id}/incidental-findings", status_code=201)
def submit_finding(
    job_id: str,
    body: SubmitFindingRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> dict:
    from src.inspection.service import submit_incidental_finding
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    _get_job_or_404(db, job_id, body.tenant_id)
    try:
        finding = submit_incidental_finding(
            db,
            job_id=job_id,
            description=body.description,
            severity=body.severity,
            location_hint=body.location_hint,
            evidence_json=body.evidence_json,
            tenant_id=body.tenant_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": finding.id, "job_id": job_id, "severity": finding.severity}


@router.post("/{job_id}/finalize")
def finalize_job_endpoint(
    job_id: str,
    body: TenantRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> ReportResponse:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    _get_job_or_404(db, job_id, body.tenant_id)
    try:
        report = finalize_inspection_job(db, job_id, tenant_id=body.tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ReportResponse(
        id=report.id,
        job_id=report.job_id,
        overall_result=report.overall_result,
        checkpoint_results_count=report.checkpoint_results_count,
        findings_count=report.findings_count,
        summary_text=report.summary_text,
    )


@router.get("/{job_id}/report")
def get_report(
    job_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> ReportResponse:
    tenant_id = principal.tenant_id
    _get_job_or_404(db, job_id, tenant_id)
    try:
        report = get_inspection_report(db, job_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return ReportResponse(
        id=report.id,
        job_id=report.job_id,
        overall_result=report.overall_result,
        checkpoint_results_count=report.checkpoint_results_count,
        findings_count=report.findings_count,
        summary_text=report.summary_text,
    )
