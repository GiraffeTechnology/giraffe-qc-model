"""API + UI handlers for LLM rule authoring (PR 22 §6, §7).

Tenant-scoped like PR 21. Proposals reuse the PR 20 proposal table + approval
workflow. There is NO Training Pack apply path here.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.qc_model.authoring import service

router = APIRouter(tags=["qc-rule-authoring"])


class ProposeBody(BaseModel):
    tenant_id: str = "default"
    created_by: Optional[str] = None


def _job_view(job) -> dict:
    return {
        "job_id": job.id,
        "tenant_id": job.tenant_id,
        "training_pack_id": job.training_pack_id,
        "source_id": job.source_id,
        "source_fragment_id": job.source_fragment_id,
        "extraction_job_id": job.extraction_job_id,
        "status": job.status,
        "provider": job.provider,
        "model": job.model,
        "proposal_count": job.proposal_count,
        "error_message": job.error_message,
    }


def proposal_view(p) -> dict:
    return {
        "proposal_id": p.id,
        "source_fragment_id": p.source_fragment_id,
        "rule_authoring_job_id": p.rule_authoring_job_id,
        "proposed_code": p.proposed_code,
        "proposed_name": p.proposed_name,
        "checkpoint_category": p.proposed_checkpoint_category,
        "ai_role": p.proposed_ai_role,
        "decision_rule": p.decision_rule,
        "review_required_conditions": p.review_required_conditions_json or [],
        "normal_visual_features": p.normal_visual_features_json or [],
        "defect_visual_features": p.defect_visual_features_json or [],
        "known_pseudo_defects": p.known_pseudo_defects_json or [],
        "questions_or_ambiguities": p.uncertainties_json or [],
        "evidence_required": p.evidence_required_json or [],
        "guard_override_note": p.guard_override_note,
        "confidence": p.confidence,
        "status": p.status,
        "approved_by": p.approved_by,
    }


# ── JSON API ──────────────────────────────────────────────────────────────


@router.post("/api/qc/source-fragments/{fragment_id}/propose-rules", status_code=201)
def propose_rules_for_fragment(
    fragment_id: str,
    body: ProposeBody = ProposeBody(),
    db: Session = Depends(get_db_dep),
):
    try:
        job = service.propose_rules_for_fragment(
            db, fragment_id, tenant_id=body.tenant_id, created_by=body.created_by
        )
    except service.FragmentNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    view = _job_view(job)
    view["proposals"] = [proposal_view(p) for p in service.list_job_proposals(db, job.id, body.tenant_id)]
    return view


@router.post("/api/qc/source-extraction-jobs/{job_id}/propose-rules", status_code=201)
def propose_rules_for_extraction_job(
    job_id: str,
    body: ProposeBody = ProposeBody(),
    db: Session = Depends(get_db_dep),
):
    job = service.propose_rules_for_extraction_job(
        db, job_id, tenant_id=body.tenant_id, created_by=body.created_by
    )
    view = _job_view(job)
    view["proposals"] = [proposal_view(p) for p in service.list_job_proposals(db, job.id, body.tenant_id)]
    return view


@router.get("/api/qc/rule-authoring-jobs/{job_id}")
def get_authoring_job(
    job_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    try:
        job = service.get_authoring_job(db, job_id, tenant_id)
    except service.AuthoringJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _job_view(job)


@router.get("/api/qc/rule-authoring-jobs/{job_id}/proposals")
def get_authoring_job_proposals(
    job_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    try:
        proposals = service.list_job_proposals(db, job_id, tenant_id)
    except service.AuthoringJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job_id, "proposals": [proposal_view(p) for p in proposals]}


# ── UI approval handlers (extend PR 21 source workbench) ──────────────────


def _sources_url(training_pack_id: str) -> str:
    return f"/admin/qc-model/training-packs/{training_pack_id}/sources"


@router.post("/admin/qc-model/training-packs/{training_pack_id}/fragments/{fragment_id}/propose")
def ui_propose_for_fragment(
    training_pack_id: str,
    fragment_id: str,
    db: Session = Depends(get_db_dep),
):
    try:
        service.propose_rules_for_fragment(db, fragment_id)
    except service.FragmentNotFound:
        pass
    return RedirectResponse(url=_sources_url(training_pack_id), status_code=303)


@router.post("/admin/qc-model/training-packs/{training_pack_id}/proposals/{proposal_id}/approve")
def ui_approve(
    training_pack_id: str,
    proposal_id: str,
    checkpoint_category: str = Form(""),
    db: Session = Depends(get_db_dep),
):
    edit = {"proposed_checkpoint_category": checkpoint_category} if checkpoint_category else None
    try:
        service.approve_proposal(db, proposal_id, "qc_supervisor", edit=edit)
    except ValueError:
        pass
    return RedirectResponse(url=_sources_url(training_pack_id), status_code=303)


@router.post("/admin/qc-model/training-packs/{training_pack_id}/proposals/{proposal_id}/reject")
def ui_reject(
    training_pack_id: str,
    proposal_id: str,
    db: Session = Depends(get_db_dep),
):
    try:
        service.reject_proposal(db, proposal_id, "qc_supervisor")
    except ValueError:
        pass
    return RedirectResponse(url=_sources_url(training_pack_id), status_code=303)
