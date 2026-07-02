"""API + UI for qualification, shadow mode, and the accuracy gate (PR 27).

Tenant-scoped. Qualification proves — with measured false-pass/false-fail rates
against human labels — that a Training Pack may move toward L3 controlled active.
A report is immutable once approved; only an approved, threshold-meeting report
unlocks ``controlled_active``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.qc_model.production.provider import ProductionProviderNotConfigured
from src.qc_model.production.runtime import TabletRuntimeNotAllowedForProduction
from src.qc_model.qualification import service
from src.qc_model.training_pack.ownership import CrossTenantTrainingPack

router = APIRouter(tags=["qc-qualification"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class CreateDatasetBody(BaseModel):
    tenant_id: str = "default"
    sku_id: Optional[str] = None
    station_id: Optional[str] = None
    name: Optional[str] = None
    created_by: Optional[str] = None


class AddSampleBody(BaseModel):
    detection_point_code: str
    sample_type: str
    image_reference: str
    human_label: str
    tenant_id: str = "default"
    metadata: Optional[dict] = None


class RunBody(BaseModel):
    tenant_id: str = "default"


class ApprovalBody(BaseModel):
    decision: str
    approved_by: str = ""
    tenant_id: str = "default"
    comment: str = ""


class ShadowBody(BaseModel):
    model_disposition: str
    human_decision: str
    tenant_id: str = "default"
    detection_point_code: Optional[str] = None
    image_reference: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None


def _run_view(r) -> dict:
    return {
        "run_id": r.id, "dataset_id": r.dataset_id, "training_pack_id": r.training_pack_id,
        "provider": r.provider, "model": r.model, "status": r.status, "error_message": r.error_message,
    }


def _report_view(rep) -> dict:
    return {
        "report_id": rep.id, "run_id": rep.run_id, "training_pack_id": rep.training_pack_id,
        "overall_meets_thresholds": rep.overall_meets_thresholds,
        "qualified_detection_point_codes": rep.qualified_detection_point_codes_json,
        "thresholds": rep.thresholds_json, "summary": rep.summary_json, "status": rep.status,
    }


# ── JSON API ─────────────────────────────────────────────────────────────────


@router.post("/api/qc/training-packs/{training_pack_id}/qualification-datasets", status_code=201)
def create_dataset(training_pack_id: str, body: CreateDatasetBody, db: Session = Depends(get_db_dep)):
    try:
        ds = service.create_dataset(
            db, training_pack_id, body.tenant_id, sku_id=body.sku_id,
            station_id=body.station_id, name=body.name, created_by=body.created_by,
        )
    except CrossTenantTrainingPack as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"dataset_id": ds.id, "training_pack_id": ds.training_pack_id, "tenant_id": ds.tenant_id}


@router.post("/api/qc/qualification-datasets/{dataset_id}/samples", status_code=201)
def add_sample(dataset_id: str, body: AddSampleBody, db: Session = Depends(get_db_dep)):
    try:
        s = service.add_sample(
            db, dataset_id, body.detection_point_code, body.sample_type,
            body.image_reference, body.human_label, body.tenant_id, body.metadata,
        )
    except service.DatasetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidSample as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"sample_id": s.id, "detection_point_code": s.detection_point_code, "human_label": s.human_label}


@router.post("/api/qc/qualification-datasets/{dataset_id}/run", status_code=201)
def run(dataset_id: str, body: RunBody = RunBody(), db: Session = Depends(get_db_dep)):
    try:
        r = service.run_qualification(db, dataset_id, body.tenant_id)
    except service.DatasetNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProductionProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (service.ProviderNotEligible, TabletRuntimeNotAllowedForProduction) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    report = service.get_report_for_run(db, r.id, body.tenant_id)
    return {"run": _run_view(r), "report": _report_view(report) if report else None}


@router.get("/api/qc/qualification-runs/{run_id}")
def get_run(run_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        r = service.get_run(db, run_id, tenant_id)
        results = service.list_results(db, run_id, tenant_id)
    except service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "run": _run_view(r),
        "results": [
            {"detection_point_code": x.detection_point_code, "false_pass_rate": x.false_pass_rate,
             "false_fail_rate": x.false_fail_rate, "false_pass": x.false_pass, "false_fail": x.false_fail,
             "sample_count": x.sample_count, "meets_thresholds": x.meets_thresholds,
             "threshold_failures": x.threshold_failures_json, "confusion": x.confusion_json}
            for x in results
        ],
    }


@router.get("/api/qc/qualification-runs/{run_id}/report")
def get_report(run_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        report = service.get_report_for_run(db, run_id, tenant_id)
    except service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if report is None:
        raise HTTPException(status_code=404, detail="no report for run")
    return _report_view(report)


@router.post("/api/qc/qualification-reports/{report_id}/approval", status_code=201)
def approve(report_id: str, body: ApprovalBody, db: Session = Depends(get_db_dep)):
    try:
        approval = service.approve_report(db, report_id, body.decision, body.approved_by, body.tenant_id, body.comment)
    except service.ReportNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ReportImmutable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.InvalidApproval as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"approval_id": approval.id, "report_id": approval.report_id,
            "decision": approval.decision, "approved_by": approval.approved_by}


@router.post("/api/qc/training-packs/{training_pack_id}/shadow-observations", status_code=201)
def add_shadow(training_pack_id: str, body: ShadowBody, db: Session = Depends(get_db_dep)):
    try:
        obs = service.record_shadow_observation(
            db, training_pack_id, body.model_disposition, body.human_decision, body.tenant_id,
            detection_point_code=body.detection_point_code, image_reference=body.image_reference,
            provider=body.provider, model=body.model,
        )
    except CrossTenantTrainingPack as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"observation_id": obs.id, "agrees": obs.agrees}


@router.get("/api/qc/training-packs/{training_pack_id}/shadow-report")
def shadow_report(training_pack_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    return service.shadow_report(db, training_pack_id, tenant_id)


# ── UI ────────────────────────────────────────────────────────────────────


@router.get("/admin/qc-model/training-packs/{training_pack_id}/qualification", response_class=HTMLResponse)
def qualification_panel(request: Request, training_pack_id: str, tenant_id: str = "default",
                        db: Session = Depends(get_db_dep)):
    from src.db.qc_qualification_models import QualificationDataset, QualificationReport
    datasets = (
        db.query(QualificationDataset)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id)
        .order_by(QualificationDataset.created_at.desc()).all()
    )
    reports = (
        db.query(QualificationReport)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id)
        .order_by(QualificationReport.created_at.desc()).all()
    )
    return templates.TemplateResponse(
        request, "qc_qualification_panel.html",
        context={
            "training_pack_id": training_pack_id, "tenant_id": tenant_id,
            "qualified": service.has_approved_qualification(db, training_pack_id, tenant_id),
            "datasets": [{"dataset_id": d.id, "name": d.name, "sku_id": d.sku_id} for d in datasets],
            "reports": [_report_view(r) for r in reports],
            "shadow": service.shadow_report(db, training_pack_id, tenant_id),
        },
    )
