"""API + UI for the Phase 2A QC rule-learning engine (PRD §13, §14).

Extends the existing FastAPI app. All endpoints are tenant-scoped. The UI at
`/admin/qc-model/learning` extends the existing Jinja2 admin UI and makes the
boundary visible: proposed rules are not active until supervisor-approved and
applied.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.qc_model.learning import apply as apply_module
from src.qc_model.learning import service
from src.qc_model.learning.schemas import LearningJobStatus

router = APIRouter(tags=["qc-learning"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ── Request bodies ────────────────────────────────────────────────────────


class CreateLearningJobBody(BaseModel):
    sku_id: str
    station_id: str
    tenant_id: str = "default"
    training_pack_id: Optional[str] = None
    created_by: Optional[str] = None
    runtime_profile: str = "server"


class OperatorRequirementBody(BaseModel):
    requirement_text: str
    source: str = "operator_text"
    operator_id: Optional[str] = None
    tenant_id: str = "default"


class SampleRefsBody(BaseModel):
    sample_refs: dict = Field(default_factory=dict)
    tenant_id: str = "default"


class RunLearningBody(BaseModel):
    requested_runtime: Optional[str] = None
    tenant_id: str = "default"


class ApproveBody(BaseModel):
    proposal_ids: list[str]
    reviewer_id: str
    edits: dict[str, dict] = Field(default_factory=dict)
    tenant_id: str = "default"


class RejectBody(BaseModel):
    proposal_ids: list[str]
    reviewer_id: str
    comment: str = ""
    tenant_id: str = "default"


class ApplyBody(BaseModel):
    applied_by: str
    tenant_id: str = "default"


def _job_view(job) -> dict:
    return {
        "learning_job_id": job.id,
        "tenant_id": job.tenant_id,
        "training_pack_id": job.training_pack_id,
        "sku_id": job.sku_id,
        "station_id": job.station_id,
        "status": job.status,
        "runtime_profile": job.runtime_profile,
        "provider": job.provider,
        "model": job.model,
        "error_message": job.error_message,
    }


def _proposal_view(p) -> dict:
    return {
        "proposal_id": p.id,
        "source_requirement": p.source_requirement,
        "proposed_code": p.proposed_code,
        "proposed_name": p.proposed_name,
        "proposed_checkpoint_category": p.proposed_checkpoint_category,
        "proposed_ai_role": p.proposed_ai_role,
        "severity": p.severity,
        "normal_visual_features": p.normal_visual_features_json or [],
        "defect_visual_features": p.defect_visual_features_json or [],
        "known_pseudo_defects": p.known_pseudo_defects_json or [],
        "decision_rule": p.decision_rule,
        "review_required_conditions": p.review_required_conditions_json or [],
        "confidence": p.confidence,
        "uncertainties": p.uncertainties_json or [],
        "status": p.status,
        "approved_by": p.approved_by,
        "applied_detection_point_id": p.applied_detection_point_id,
    }


# ── Learning jobs ─────────────────────────────────────────────────────────


@router.post("/api/qc/training-packs/{training_pack_id}/learning-jobs")
def create_learning_job(
    training_pack_id: str,
    body: CreateLearningJobBody,
    db: Session = Depends(get_db_dep),
):
    job = service.create_learning_job(
        db,
        training_pack_id=training_pack_id,
        sku_id=body.sku_id,
        station_id=body.station_id,
        tenant_id=body.tenant_id,
        created_by=body.created_by,
        runtime_profile=body.runtime_profile,
    )
    return _job_view(job)


@router.get("/api/qc/learning-jobs/{learning_job_id}")
def get_learning_job(
    learning_job_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    try:
        job = service.get_job(db, learning_job_id, tenant_id)
    except service.LearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    view = _job_view(job)
    view["detection_point_proposals"] = [
        _proposal_view(p) for p in service.list_detection_point_proposals(db, job.id, tenant_id)
    ]
    return view


@router.get("/api/qc/training-packs/{training_pack_id}/learning-jobs")
def list_learning_jobs(
    training_pack_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    from src.db.qc_learning_models import QCLearningJob

    jobs = (
        db.query(QCLearningJob)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id)
        .all()
    )
    return {"training_pack_id": training_pack_id, "learning_jobs": [_job_view(j) for j in jobs]}


# ── Inputs ────────────────────────────────────────────────────────────────


@router.post("/api/qc/learning-jobs/{learning_job_id}/operator-requirements")
def add_operator_requirement(
    learning_job_id: str,
    body: OperatorRequirementBody,
    db: Session = Depends(get_db_dep),
):
    try:
        inp = service.add_operator_requirement(
            db,
            learning_job_id=learning_job_id,
            requirement_text=body.requirement_text,
            source=body.source,
            operator_id=body.operator_id,
            tenant_id=body.tenant_id,
        )
    except service.LearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"input_id": inp.id, "learning_job_id": learning_job_id, "input_type": inp.input_type}


@router.post("/api/qc/learning-jobs/{learning_job_id}/sample-refs")
def add_sample_refs(
    learning_job_id: str,
    body: SampleRefsBody,
    db: Session = Depends(get_db_dep),
):
    try:
        inp = service.add_sample_refs(
            db, learning_job_id=learning_job_id, sample_refs=body.sample_refs, tenant_id=body.tenant_id
        )
    except service.LearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"input_id": inp.id, "learning_job_id": learning_job_id, "input_type": inp.input_type}


# ── Run learning ──────────────────────────────────────────────────────────


@router.post("/api/qc/learning-jobs/{learning_job_id}/run")
def run_learning(
    learning_job_id: str,
    body: RunLearningBody = RunLearningBody(),
    db: Session = Depends(get_db_dep),
):
    try:
        job = service.run_learning(
            db,
            learning_job_id=learning_job_id,
            tenant_id=body.tenant_id,
            requested_runtime=body.requested_runtime,
        )
    except service.LearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    view = _job_view(job)
    view["detection_point_proposals"] = [
        _proposal_view(p) for p in service.list_detection_point_proposals(db, job.id, body.tenant_id)
    ]
    return view


# ── Report ────────────────────────────────────────────────────────────────


@router.get("/api/qc/learning-jobs/{learning_job_id}/report")
def get_report(
    learning_job_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    report = service.get_report(db, learning_job_id, tenant_id)
    if report is None:
        raise HTTPException(status_code=404, detail="No report for this learning job yet")
    return report


# ── Approval / apply ──────────────────────────────────────────────────────


@router.post("/api/qc/learning-jobs/{learning_job_id}/approve-proposals")
def approve_proposals(
    learning_job_id: str,
    body: ApproveBody,
    db: Session = Depends(get_db_dep),
):
    try:
        job = service.approve_proposals(
            db, learning_job_id, body.proposal_ids, body.reviewer_id, body.edits, body.tenant_id
        )
    except service.LearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _job_view(job)


@router.post("/api/qc/learning-jobs/{learning_job_id}/reject-proposals")
def reject_proposals(
    learning_job_id: str,
    body: RejectBody,
    db: Session = Depends(get_db_dep),
):
    try:
        job = service.reject_proposals(
            db, learning_job_id, body.proposal_ids, body.reviewer_id, body.comment, body.tenant_id
        )
    except service.LearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _job_view(job)


@router.post("/api/qc/learning-jobs/{learning_job_id}/apply-approved-rules")
def apply_approved_rules(
    learning_job_id: str,
    body: ApplyBody,
    db: Session = Depends(get_db_dep),
):
    try:
        result = apply_module.apply_approved_rules(
            db, learning_job_id, applied_by=body.applied_by, tenant_id=body.tenant_id
        )
    except service.LearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return result


# ── UI (extends existing admin UI) ────────────────────────────────────────


@router.get("/admin/qc-model/learning", response_class=HTMLResponse)
def learning_panel(
    request: Request,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    from src.db.qc_learning_models import QCLearningJob

    jobs = db.query(QCLearningJob).filter_by(tenant_id=tenant_id).order_by(
        QCLearningJob.created_at.desc()
    ).all()
    job_rows = []
    for job in jobs:
        job_rows.append(
            {
                "job": _job_view(job),
                "proposals": [
                    _proposal_view(p)
                    for p in service.list_detection_point_proposals(db, job.id, tenant_id)
                ],
            }
        )
    return templates.TemplateResponse(
        request,
        "qc_learning_panel.html",
        context={
            "job_rows": job_rows,
            "statuses": [s.value for s in LearningJobStatus],
            "tenant_id": tenant_id,
        },
    )


_LEARNING_PANEL_URL = "/admin/qc-model/learning"


@router.post("/admin/qc-model/learning/create")
def ui_create_job(
    training_pack_id: str = Form(...),
    sku_id: str = Form(...),
    station_id: str = Form(...),
    db: Session = Depends(get_db_dep),
):
    service.create_learning_job(
        db, training_pack_id=training_pack_id, sku_id=sku_id, station_id=station_id
    )
    return RedirectResponse(url=_LEARNING_PANEL_URL, status_code=303)


@router.post("/admin/qc-model/learning/{learning_job_id}/add-requirement")
def ui_add_requirement(
    learning_job_id: str,
    requirement_text: str = Form(...),
    db: Session = Depends(get_db_dep),
):
    if requirement_text.strip():
        service.add_operator_requirement(db, learning_job_id, requirement_text)
    return RedirectResponse(url=_LEARNING_PANEL_URL, status_code=303)


@router.post("/admin/qc-model/learning/{learning_job_id}/run")
def ui_run(learning_job_id: str, db: Session = Depends(get_db_dep)):
    service.run_learning(db, learning_job_id)
    return RedirectResponse(url=_LEARNING_PANEL_URL, status_code=303)


@router.post("/admin/qc-model/learning/{learning_job_id}/approve/{proposal_id}")
def ui_approve(learning_job_id: str, proposal_id: str, db: Session = Depends(get_db_dep)):
    service.approve_proposals(db, learning_job_id, [proposal_id], "qc_supervisor")
    return RedirectResponse(url=_LEARNING_PANEL_URL, status_code=303)


@router.post("/admin/qc-model/learning/{learning_job_id}/reject/{proposal_id}")
def ui_reject(learning_job_id: str, proposal_id: str, db: Session = Depends(get_db_dep)):
    service.reject_proposals(db, learning_job_id, [proposal_id], "qc_supervisor")
    return RedirectResponse(url=_LEARNING_PANEL_URL, status_code=303)


@router.post("/admin/qc-model/learning/{learning_job_id}/apply")
def ui_apply(learning_job_id: str, db: Session = Depends(get_db_dep)):
    apply_module.apply_approved_rules(db, learning_job_id, applied_by="qc_supervisor")
    return RedirectResponse(url=_LEARNING_PANEL_URL, status_code=303)
