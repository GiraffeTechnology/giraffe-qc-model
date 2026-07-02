"""API + UI for Production Assisted Mode (PR 25).

Tenant-scoped. A run only ever produces a *recommended* disposition; the final
pass/reject/review decision is a mandatory human action recorded in an
append-only audit trail. No endpoint auto-finalizes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.qc_model.production import service
from src.qc_model.training_pack.ownership import CrossTenantTrainingPack

router = APIRouter(tags=["qc-production"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class CreateSessionBody(BaseModel):
    training_pack_id: str
    tenant_id: str = "default"
    sku_id: Optional[str] = None
    station_id: Optional[str] = None
    operator_id: Optional[str] = None


class CaptureBody(BaseModel):
    image_reference: str
    tenant_id: str = "default"
    capture_metadata: Optional[dict] = None


class RunBody(BaseModel):
    tenant_id: str = "default"


class FinalDecisionBody(BaseModel):
    decision: str
    decided_by: str = ""
    tenant_id: str = "default"
    comment: str = ""


def _session_view(s) -> dict:
    return {
        "session_id": s.id, "tenant_id": s.tenant_id, "training_pack_id": s.training_pack_id,
        "sku_id": s.sku_id, "station_id": s.station_id, "operator_id": s.operator_id,
        "production_mode": s.production_mode, "status": s.status,
    }


def _run_view(r) -> dict:
    return {
        "run_id": r.id, "tenant_id": r.tenant_id, "session_id": r.session_id,
        "training_pack_id": r.training_pack_id, "provider": r.provider, "model": r.model,
        "prompt_schema_version": r.prompt_schema_version, "status": r.status,
        "overall_disposition": r.overall_disposition,
        "detection_result_count": r.detection_result_count, "error_message": r.error_message,
    }


def _result_view(d) -> dict:
    return {
        "detection_point_code": d.detection_point_code, "disposition": d.disposition,
        "checkpoint_category": d.checkpoint_category,
        "confirmed_visual_rule_id": d.confirmed_visual_rule_id,
        "visual_rule_memory_id": d.visual_rule_memory_id,
        "evidence_regions": d.evidence_regions_json,
        "observed_features": d.observed_features_json, "defect_features": d.defect_features_json,
        "review_required_conditions": d.review_required_conditions_json,
        "confidence": d.confidence, "uncertainty": d.uncertainty,
        "provider": d.provider, "model": d.model, "source_image_reference": d.source_image_reference,
    }


# ── JSON API ─────────────────────────────────────────────────────────────────


@router.post("/api/qc/production/inspection-sessions", status_code=201)
def create_session(body: CreateSessionBody, db: Session = Depends(get_db_dep)):
    try:
        s = service.create_session(
            db, body.training_pack_id, body.tenant_id,
            sku_id=body.sku_id, station_id=body.station_id, operator_id=body.operator_id,
        )
    except CrossTenantTrainingPack as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ReadinessNotMet as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _session_view(s)


@router.get("/api/qc/production/inspection-sessions/{session_id}")
def get_session(session_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        s = service.get_session(db, session_id, tenant_id)
    except service.SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _session_view(s)


@router.post("/api/qc/production/inspection-sessions/{session_id}/captures", status_code=201)
def add_capture(session_id: str, body: CaptureBody, db: Session = Depends(get_db_dep)):
    try:
        c = service.add_capture(db, session_id, body.image_reference, body.tenant_id, body.capture_metadata)
    except service.SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"capture_id": c.id, "session_id": c.session_id, "image_reference": c.image_reference}


@router.post("/api/qc/production/inspection-sessions/{session_id}/run", status_code=201)
def run_session(session_id: str, body: RunBody = RunBody(), db: Session = Depends(get_db_dep)):
    try:
        run = service.run_inspection(db, session_id, body.tenant_id)
    except service.SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.ReadinessNotMet as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.ProviderNotEligible as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.NoCaptures as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _run_view(run)


@router.get("/api/qc/production/inspection-runs/{run_id}")
def get_run(run_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        run = service.get_run(db, run_id, tenant_id)
        results = service.list_detection_results(db, run_id, tenant_id)
    except service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run": _run_view(run), "detection_results": [_result_view(d) for d in results]}


@router.get("/api/qc/production/inspection-runs/{run_id}/evidence")
def get_evidence(run_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        packet = service.get_evidence_packet(db, run_id, tenant_id)
    except service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if packet is None:
        raise HTTPException(status_code=404, detail="no evidence packet for run")
    return {"run_id": run_id, "packet": packet.packet_json}


@router.post("/api/qc/production/inspection-runs/{run_id}/final-decision", status_code=201)
def final_decision(run_id: str, body: FinalDecisionBody, db: Session = Depends(get_db_dep)):
    try:
        record = service.record_final_decision(
            db, run_id, body.decision, body.decided_by, body.tenant_id, body.comment
        )
    except service.RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidFinalDecision as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "final_decision_id": record.id, "run_id": record.run_id,
        "decision": record.decision, "decided_by": record.decided_by,
        "recommended_disposition": record.recommended_disposition,
    }


# ── UI (existing FastAPI + Jinja2 admin style) ───────────────────────────────


@router.get("/admin/qc-model/production", response_class=HTMLResponse)
def production_home(request: Request, training_pack_id: str = "", tenant_id: str = "default",
                    db: Session = Depends(get_db_dep)):
    from src.db.qc_production_models import ProductionInspectionSession
    sessions = []
    if training_pack_id:
        sessions = (
            db.query(ProductionInspectionSession)
            .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id)
            .order_by(ProductionInspectionSession.created_at.desc()).all()
        )
    return templates.TemplateResponse(
        request, "qc_production_panel.html",
        context={
            "training_pack_id": training_pack_id, "tenant_id": tenant_id,
            "sessions": [_session_view(s) for s in sessions], "session": None,
            "captures": [], "runs": [], "results": [], "final_decisions": [],
        },
    )


@router.get("/admin/qc-model/production/sessions/{session_id}", response_class=HTMLResponse)
def production_session(request: Request, session_id: str, tenant_id: str = "default",
                       db: Session = Depends(get_db_dep)):
    from src.db.qc_production_models import ProductionInspectionRun
    try:
        s = service.get_session(db, session_id, tenant_id)
    except service.SessionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    captures = service.list_captures(db, session_id, tenant_id)
    runs = (
        db.query(ProductionInspectionRun)
        .filter_by(session_id=session_id, tenant_id=tenant_id)
        .order_by(ProductionInspectionRun.created_at.desc()).all()
    )
    latest = runs[0] if runs else None
    results = service.list_detection_results(db, latest.id, tenant_id) if latest else []
    decisions = service.get_final_decisions(db, latest.id, tenant_id) if latest else []
    return templates.TemplateResponse(
        request, "qc_production_panel.html",
        context={
            "training_pack_id": s.training_pack_id, "tenant_id": tenant_id,
            "sessions": [], "session": _session_view(s),
            "captures": [{"image_reference": c.image_reference} for c in captures],
            "runs": [_run_view(r) for r in runs],
            "results": [_result_view(d) for d in results],
            "latest_run": _run_view(latest) if latest else None,
            "final_decisions": [
                {"decision": d.decision, "decided_by": d.decided_by, "comment": d.comment}
                for d in decisions
            ],
        },
    )


@router.post("/admin/qc-model/production/sessions/{session_id}/captures")
def ui_add_capture(session_id: str, image_reference: str = Form(...), tenant_id: str = Form("default"),
                   db: Session = Depends(get_db_dep)):
    try:
        service.add_capture(db, session_id, image_reference, tenant_id)
    except service.SessionNotFound:
        pass
    return _session_redirect(session_id, tenant_id)


@router.post("/admin/qc-model/production/sessions/{session_id}/run")
def ui_run(session_id: str, tenant_id: str = Form("default"), db: Session = Depends(get_db_dep)):
    try:
        service.run_inspection(db, session_id, tenant_id)
    except (service.SessionNotFound, service.ReadinessNotMet, service.ProviderNotEligible, service.NoCaptures):
        pass
    return _session_redirect(session_id, tenant_id)


@router.post("/admin/qc-model/production/runs/{run_id}/final-decision")
def ui_final_decision(run_id: str, decision: str = Form(...), decided_by: str = Form(...),
                      comment: str = Form(""), tenant_id: str = Form("default"),
                      db: Session = Depends(get_db_dep)):
    session_id = ""
    try:
        run = service.get_run(db, run_id, tenant_id)
        session_id = run.session_id
        service.record_final_decision(db, run_id, decision, decided_by, tenant_id, comment)
    except (service.RunNotFound, service.InvalidFinalDecision):
        pass
    return _session_redirect(session_id, tenant_id)


def _session_redirect(session_id: str, tenant_id: str) -> RedirectResponse:
    suffix = f"?tenant_id={tenant_id}" if tenant_id and tenant_id != "default" else ""
    return RedirectResponse(
        url=f"/admin/qc-model/production/sessions/{session_id}{suffix}", status_code=303
    )
