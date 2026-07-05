"""API + UI for VLM sample learning (PR 23 §4, §5).

Tenant-scoped like PR 21/22. Approve and apply are two distinct steps; apply is
the only Training-Pack writer and is gated server-side on approved status +
no-silent-overwrite conflict detection.
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
from src.qc_model.sample_learning import service
from src.qc_model.sample_learning.types import SampleType

router = APIRouter(tags=["qc-sample-learning"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class CreateSampleGroupBody(BaseModel):
    detection_point_id: str
    sample_type: str
    image_references: list[str] = Field(default_factory=list)
    tenant_id: str = "default"
    created_by: Optional[str] = None


class CreateJobBody(BaseModel):
    sample_group_id: str
    tenant_id: str = "default"
    created_by: Optional[str] = None


class ApprovalBody(BaseModel):
    action: str  # approve | edit | reject
    reviewer_id: str
    edit: Optional[dict] = None
    comment: str = ""
    tenant_id: str = "default"


class ApplyBody(BaseModel):
    memory_id: str
    applied_by: str
    tenant_id: str = "default"


def _group_view(g) -> dict:
    return {
        "sample_group_id": g.id, "training_pack_id": g.training_pack_id,
        "detection_point_id": g.detection_point_id, "detection_point_code": g.detection_point_code,
        "sample_type": g.sample_type, "samples": g.samples_json or [], "status": g.status,
    }


def _job_view(j) -> dict:
    return {
        "job_id": j.id, "training_pack_id": j.training_pack_id, "sample_group_id": j.sample_group_id,
        "status": j.status, "provider": j.provider, "model": j.model,
        "observation_count": j.observation_count, "error_message": j.error_message,
    }


def _obs_view(o) -> dict:
    return {
        "observation_id": o.id, "source_sample_id": o.source_sample_id,
        "image_reference": o.image_reference, "detection_point_code": o.detection_point_code,
        "feature_type": o.feature_type, "evidence_region": o.evidence_region_json,
        "confidence": o.confidence, "uncertainty": o.uncertainty,
        "rule_implication": o.rule_implication, "requires_human_review": o.requires_human_review,
        "normal_visual_features": o.normal_visual_features_json or [],
        "acceptable_variations": o.acceptable_variations_json or [],
        "defect_visual_features": o.defect_visual_features_json or [],
        "known_pseudo_defects": o.known_pseudo_defects_json or [],
        "capture_artifact_risks": o.capture_artifact_risks_json or [],
        "evidence_required": o.evidence_required_json or [],
        "review_required_conditions": o.review_required_conditions_json or [],
    }


def _memory_view(m) -> dict:
    return {
        "memory_id": m.id, "training_pack_id": m.training_pack_id,
        "detection_point_code": m.detection_point_code, "feature_type": m.feature_type,
        "status": m.status, "approved_by": m.approved_by,
        "normal_visual_features": m.normal_visual_features_json or [],
        "acceptable_variations": m.acceptable_variations_json or [],
        "defect_visual_features": m.defect_visual_features_json or [],
        "known_pseudo_defects": m.known_pseudo_defects_json or [],
        "capture_artifact_risks": m.capture_artifact_risks_json or [],
    }


# ── JSON API ──────────────────────────────────────────────────────────────


@router.post("/api/qc/training-packs/{training_pack_id}/sample-groups", status_code=201)
def create_sample_group(training_pack_id: str, body: CreateSampleGroupBody, db: Session = Depends(get_db_dep)):
    try:
        g = service.create_sample_group(
            db, training_pack_id=training_pack_id, detection_point_id=body.detection_point_id,
            sample_type=body.sample_type, image_references=body.image_references,
            tenant_id=body.tenant_id, created_by=body.created_by,
        )
    except service.InvalidSampleType as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except service.DetectionPointNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _group_view(g)


@router.post("/api/qc/training-packs/{training_pack_id}/sample-learning-jobs", status_code=201)
def create_learning_job(training_pack_id: str, body: CreateJobBody, db: Session = Depends(get_db_dep)):
    try:
        group = service.get_sample_group(db, body.sample_group_id, body.tenant_id)
    except service.SampleGroupNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if group.training_pack_id != training_pack_id:
        raise HTTPException(status_code=404, detail="sample group does not belong to this training pack")
    job = service.run_sample_learning_job(db, body.sample_group_id, body.tenant_id, created_by=body.created_by)
    return _job_view(job)


@router.get("/api/qc/sample-learning-jobs/{job_id}")
def get_learning_job(job_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        return _job_view(service.get_job(db, job_id, tenant_id))
    except service.SampleLearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/qc/sample-learning-jobs/{job_id}/observations")
def get_observations(job_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        obs = service.list_observations(db, job_id, tenant_id)
    except service.SampleLearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job_id, "observations": [_obs_view(o) for o in obs]}


@router.get("/api/qc/sample-learning-jobs/{job_id}/visual-rule-memory")
def get_visual_rule_memory(job_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        mem = service.list_visual_rule_memory(db, job_id, tenant_id)
    except service.SampleLearningJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job_id, "visual_rule_memory": [_memory_view(m) for m in mem]}


@router.post("/api/qc/visual-rule-memory/{memory_id}/approval")
def approve_memory(memory_id: str, body: ApprovalBody, db: Session = Depends(get_db_dep)):
    try:
        m = service.review_memory(
            db, memory_id, body.action, body.reviewer_id, body.tenant_id, body.edit, body.comment
        )
    except service.MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _memory_view(m)


@router.post("/api/qc/training-packs/{training_pack_id}/apply-approved-visual-rule-memory")
def apply_memory(training_pack_id: str, body: ApplyBody, db: Session = Depends(get_db_dep)):
    try:
        confirmed = service.apply_approved_memory(
            db, training_pack_id, body.memory_id, body.applied_by, body.tenant_id
        )
    except service.MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.MemoryPackMismatch as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.MemoryNotApproved as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.ConfirmedRuleConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "confirmed_rule_id": confirmed.id, "training_pack_id": confirmed.training_pack_id,
        "detection_point_code": confirmed.detection_point_code, "feature_type": confirmed.feature_type,
        "source_memory_id": confirmed.source_memory_id, "confirmed_by": confirmed.confirmed_by,
    }


# ── UI ────────────────────────────────────────────────────────────────────


@router.get("/admin/qc-model/training-packs/{training_pack_id}/sample-learning", response_class=HTMLResponse)
def sample_learning_panel(
    request: Request, training_pack_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)
):
    from src.db.qc_sample_learning_models import SampleGroup, SampleLearningJob
    from src.db.sku_models import QCDetectionPoint

    groups = db.query(SampleGroup).filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id).all()
    group_rows = []
    for g in groups:
        jobs = (
            db.query(SampleLearningJob)
            .filter_by(sample_group_id=g.id, tenant_id=tenant_id)
            .order_by(SampleLearningJob.created_at.desc())
            .all()
        )
        latest = jobs[0] if jobs else None
        obs = service.list_observations(db, latest.id, tenant_id) if latest and latest.status == "completed" else []
        mem = service.list_visual_rule_memory(db, latest.id, tenant_id) if latest and latest.status == "completed" else []
        group_rows.append({
            "group": _group_view(g),
            "latest_job": _job_view(latest) if latest else None,
            "observations": [_obs_view(o) for o in obs],
            "memory": [_memory_view(m) for m in mem],
        })
    detection_points = db.query(QCDetectionPoint).filter_by(tenant_id=tenant_id).all()
    return templates.TemplateResponse(
        request, "qc_sample_learning_panel.html",
        context={
            "training_pack_id": training_pack_id, "tenant_id": tenant_id,
            "sample_types": [t.value for t in SampleType],
            "detection_points": [{"id": d.id, "code": d.point_code, "label": d.label} for d in detection_points],
            "group_rows": group_rows,
        },
    )


def _panel_url(tp: str, tenant_id: str = "default") -> str:
    suffix = f"?tenant_id={tenant_id}" if tenant_id and tenant_id != "default" else ""
    return f"/admin/qc-model/training-packs/{tp}/sample-learning{suffix}"


@router.post("/admin/qc-model/training-packs/{training_pack_id}/sample-groups")
def ui_create_group(
    training_pack_id: str,
    detection_point_id: str = Form(...),
    sample_type: str = Form(...),
    image_references: str = Form(""),
    tenant_id: str = Form("default"),
    db: Session = Depends(get_db_dep),
):
    refs = [r.strip() for r in image_references.split(",") if r.strip()]
    try:
        service.create_sample_group(
            db, training_pack_id, detection_point_id, sample_type, refs, tenant_id=tenant_id
        )
    except (service.InvalidSampleType, service.DetectionPointNotFound):
        pass
    return RedirectResponse(url=_panel_url(training_pack_id, tenant_id), status_code=303)


@router.post("/admin/qc-model/training-packs/{training_pack_id}/sample-groups/{group_id}/learn")
def ui_learn(
    training_pack_id: str,
    group_id: str,
    tenant_id: str = Form("default"),
    db: Session = Depends(get_db_dep),
):
    try:
        service.run_sample_learning_job(db, group_id, tenant_id)
    except service.SampleGroupNotFound:
        pass
    return RedirectResponse(url=_panel_url(training_pack_id, tenant_id), status_code=303)


# NOTE: the dedicated /apply route MUST be registered before the generic
# /{action} catch-all — FastAPI matches routes in registration order, so a
# later /{action} route would otherwise shadow /apply and silently no-op it.
@router.post("/admin/qc-model/training-packs/{training_pack_id}/memory/{memory_id}/apply")
def ui_apply(
    training_pack_id: str,
    memory_id: str,
    tenant_id: str = Form("default"),
    db: Session = Depends(get_db_dep),
):
    try:
        service.apply_approved_memory(db, training_pack_id, memory_id, "qc_supervisor", tenant_id)
    except (
        service.MemoryNotFound,
        service.MemoryPackMismatch,
        service.MemoryNotApproved,
        service.ConfirmedRuleConflict,
    ):
        pass
    return RedirectResponse(url=_panel_url(training_pack_id, tenant_id), status_code=303)


@router.post("/admin/qc-model/training-packs/{training_pack_id}/memory/{memory_id}/{action}")
def ui_review(
    training_pack_id: str,
    memory_id: str,
    action: str,
    tenant_id: str = Form("default"),
    db: Session = Depends(get_db_dep),
):
    if action in ("approve", "reject"):
        try:
            service.review_memory(db, memory_id, action, "qc_supervisor", tenant_id)
        except (service.MemoryNotFound, ValueError):
            pass
    return RedirectResponse(url=_panel_url(training_pack_id, tenant_id), status_code=303)
