"""API + UI for false-pass incident response & requalification (PR 28).

Tenant-scoped. A confirmed false pass (P0) suspends L3 ``controlled_active`` for
the affected scope and requires a new supervisor-approved, threshold-meeting
qualification report before L3 can be restored. Nothing here auto-finalizes or
bypasses readiness; L2 ``production_assisted`` (human-final) stays available.
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
from src.qc_model.incident import service
from src.qc_model.training_pack.ownership import CrossTenantTrainingPack

router = APIRouter(tags=["qc-incident"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class ReportIncidentBody(BaseModel):
    training_pack_id: str
    incident_type: str = "false_pass"
    tenant_id: str = "default"
    sku_id: Optional[str] = None
    station_id: Optional[str] = None
    detection_point_code: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    inspection_session_id: Optional[str] = None
    inspection_run_id: Optional[str] = None
    production_detection_result_id: Optional[str] = None
    qualification_run_id: Optional[str] = None
    qualification_report_id: Optional[str] = None
    shadow_observation_id: Optional[str] = None
    reported_by: Optional[str] = None
    reported_role: Optional[str] = None
    report_source: Optional[str] = None
    description: Optional[str] = None
    evidence_refs_json: Optional[list] = None
    model_output_json: Optional[dict] = None
    human_or_downstream_decision_json: Optional[dict] = None


class ConfirmBody(BaseModel):
    confirmation_decision: str
    confirmed_by: str = ""
    tenant_id: str = "default"
    confirmation_role: str = "supervisor"
    confirmation_reason: str = ""
    evidence_refs_json: Optional[list] = None


class LiftBody(BaseModel):
    lifted_by: str = ""
    requalification_report_id: str = ""
    tenant_id: str = "default"
    lift_role: str = "supervisor"
    lift_reason: str = ""


def _incident_view(i) -> dict:
    return {
        "incident_id": i.id, "tenant_id": i.tenant_id, "incident_type": i.incident_type,
        "severity": i.severity, "status": i.status, "training_pack_id": i.training_pack_id,
        "sku_id": i.sku_id, "station_id": i.station_id, "detection_point_code": i.detection_point_code,
        "provider": i.provider, "model": i.model, "affected_scope": i.affected_scope_json,
        "confirmed_by": i.confirmed_by,
    }


def _suspension_view(s) -> dict:
    return {
        "suspension_id": s.id, "incident_id": s.incident_id, "training_pack_id": s.training_pack_id,
        "suspension_type": s.suspension_type, "status": s.status, "scope": s.scope_json,
        "requalification_report_id": s.requalification_report_id,
    }


# ── JSON API ─────────────────────────────────────────────────────────────────


@router.post("/api/qc/incidents", status_code=201)
def report_incident(body: ReportIncidentBody, db: Session = Depends(get_db_dep)):
    try:
        inc = service.report_incident(
            db, body.training_pack_id, body.incident_type, body.tenant_id,
            sku_id=body.sku_id, station_id=body.station_id, detection_point_code=body.detection_point_code,
            provider=body.provider, model=body.model, inspection_session_id=body.inspection_session_id,
            inspection_run_id=body.inspection_run_id,
            production_detection_result_id=body.production_detection_result_id,
            qualification_run_id=body.qualification_run_id, qualification_report_id=body.qualification_report_id,
            shadow_observation_id=body.shadow_observation_id, reported_by=body.reported_by,
            reported_role=body.reported_role, report_source=body.report_source, description=body.description,
            evidence_refs=body.evidence_refs_json, model_output=body.model_output_json,
            human_or_downstream_decision=body.human_or_downstream_decision_json,
        )
    except CrossTenantTrainingPack as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidIncident as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _incident_view(inc)


@router.get("/api/qc/incidents/{incident_id}")
def get_incident(incident_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        bundle = service.get_incident_bundle(db, incident_id, tenant_id)
    except service.IncidentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "incident": _incident_view(bundle["incident"]),
        "suspensions": [_suspension_view(s) for s in bundle["suspensions"]],
        "requalification_requirements": [
            {"id": r.id, "status": r.status, "previous_qualification_report_id": r.previous_qualification_report_id,
             "satisfied_by_report_id": r.satisfied_by_report_id}
            for r in bundle["requalification_requirements"]
        ],
        "audit_events": [
            {"event_type": a.event_type, "actor_id": a.actor_id, "actor_role": a.actor_role,
             "payload": a.event_payload_json}
            for a in bundle["audit_events"]
        ],
    }


@router.post("/api/qc/incidents/{incident_id}/confirmation", status_code=201)
def confirm_incident(incident_id: str, body: ConfirmBody, db: Session = Depends(get_db_dep)):
    try:
        inc = service.confirm_incident(
            db, incident_id, body.confirmation_decision, body.confirmed_by, body.tenant_id,
            confirmation_role=body.confirmation_role, confirmation_reason=body.confirmation_reason,
            evidence_refs=body.evidence_refs_json,
        )
    except service.IncidentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidConfirmation as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _incident_view(inc)


@router.get("/api/qc/suspensions")
def list_suspensions(tenant_id: str = "default", training_pack_id: Optional[str] = None,
                     active_only: bool = True, db: Session = Depends(get_db_dep)):
    suspensions = service.list_suspensions(db, tenant_id, training_pack_id, active_only)
    return {"suspensions": [_suspension_view(s) for s in suspensions]}


@router.post("/api/qc/suspensions/{suspension_id}/lift", status_code=201)
def lift_suspension(suspension_id: str, body: LiftBody, db: Session = Depends(get_db_dep)):
    try:
        s = service.lift_suspension(
            db, suspension_id, body.lifted_by, body.requalification_report_id, body.tenant_id,
            lift_role=body.lift_role, lift_reason=body.lift_reason,
        )
    except service.SuspensionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidLift as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _suspension_view(s)


# ── UI ────────────────────────────────────────────────────────────────────


@router.get("/admin/qc-model/incidents", response_class=HTMLResponse)
def incidents_home(request: Request, tenant_id: str = "default", training_pack_id: str = "",
                   error: str = "", db: Session = Depends(get_db_dep)):
    from src.db.qc_incident_models import QCQualityIncident
    q = db.query(QCQualityIncident).filter_by(tenant_id=tenant_id)
    if training_pack_id:
        q = q.filter_by(training_pack_id=training_pack_id)
    incidents = q.order_by(QCQualityIncident.created_at.desc()).all()
    return templates.TemplateResponse(
        request, "qc_incident_panel.html",
        context={"tenant_id": tenant_id, "training_pack_id": training_pack_id, "error": error,
                 "incidents": [_incident_view(i) for i in incidents], "incident": None,
                 "suspensions": [], "requals": [], "audit": [],
                 "active_suspensions": [_suspension_view(s) for s in service.list_suspensions(db, tenant_id)]},
    )


@router.get("/admin/qc-model/incidents/{incident_id}", response_class=HTMLResponse)
def incident_detail(request: Request, incident_id: str, tenant_id: str = "default", error: str = "",
                    db: Session = Depends(get_db_dep)):
    try:
        bundle = service.get_incident_bundle(db, incident_id, tenant_id)
    except service.IncidentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request, "qc_incident_panel.html",
        context={
            "tenant_id": tenant_id, "training_pack_id": bundle["incident"].training_pack_id, "error": error,
            "incidents": [], "incident": _incident_view(bundle["incident"]),
            "suspensions": [_suspension_view(s) for s in bundle["suspensions"]],
            "requals": [{"id": r.id, "status": r.status} for r in bundle["requalification_requirements"]],
            "audit": [{"event_type": a.event_type, "actor_id": a.actor_id} for a in bundle["audit_events"]],
            "active_suspensions": [],
        },
    )


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=303)


@router.post("/admin/qc-model/incidents")
def ui_report(training_pack_id: str = Form(...), tenant_id: str = Form("default"),
              detection_point_code: str = Form(""), reported_by: str = Form("qc_supervisor"),
              description: str = Form(""), db: Session = Depends(get_db_dep)):
    error = ""
    incident_id = ""
    try:
        inc = service.report_incident(
            db, training_pack_id, "false_pass", tenant_id,
            detection_point_code=detection_point_code or None, reported_by=reported_by, description=description,
        )
        incident_id = inc.id
    except (service.InvalidIncident, CrossTenantTrainingPack) as exc:
        error = str(exc)
    if error:
        return _redirect(f"/admin/qc-model/incidents?tenant_id={tenant_id}&error={error}")
    return _redirect(f"/admin/qc-model/incidents/{incident_id}?tenant_id={tenant_id}")


@router.post("/admin/qc-model/incidents/{incident_id}/confirmation")
def ui_confirm(incident_id: str, confirmation_decision: str = Form(...), confirmed_by: str = Form(...),
               confirmation_reason: str = Form(""), tenant_id: str = Form("default"),
               db: Session = Depends(get_db_dep)):
    error = ""
    try:
        service.confirm_incident(db, incident_id, confirmation_decision, confirmed_by, tenant_id,
                                 confirmation_reason=confirmation_reason)
    except (service.InvalidConfirmation, service.IncidentNotFound) as exc:
        error = str(exc)
    suffix = f"?tenant_id={tenant_id}" + (f"&error={error}" if error else "")
    return _redirect(f"/admin/qc-model/incidents/{incident_id}{suffix}")


@router.post("/admin/qc-model/suspensions/{suspension_id}/lift")
def ui_lift(suspension_id: str, lifted_by: str = Form(...), requalification_report_id: str = Form(...),
            lift_reason: str = Form(""), incident_id: str = Form(""), tenant_id: str = Form("default"),
            db: Session = Depends(get_db_dep)):
    error = ""
    try:
        service.lift_suspension(db, suspension_id, lifted_by, requalification_report_id, tenant_id,
                                lift_reason=lift_reason)
    except (service.InvalidLift, service.SuspensionNotFound) as exc:
        error = str(exc)
    target = f"/admin/qc-model/incidents/{incident_id}" if incident_id else "/admin/qc-model/incidents"
    suffix = f"?tenant_id={tenant_id}" + (f"&error={error}" if error else "")
    return _redirect(f"{target}{suffix}")
