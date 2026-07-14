"""API + admin UI for server verdict recomputation and the Results page (§9).

Receives Pad verdict submissions, recomputes the authoritative verdict server-
side (never trusting the Pad's claim), and renders `/admin/results`. Does not
implement Pad-side submission (S6 owns that).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.api.authz import effective_actor
from src.qc_model.verdict import service
from src.qc_model.verdict.service import SubmissionNotFound
from src.web.i18n import install_i18n

router = APIRouter(tags=["qc-results"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
# Carry the shared web-shell language switch on the Results page.
install_i18n(templates)


class CheckpointResultIn(BaseModel):
    checkpoint_id: str
    result: str


class SubmitVerdictBody(BaseModel):
    tenant_id: str = "default"
    job_ref: str
    standard_revision_id: str
    bundle_version: str = ""
    pad_overall_result: str
    checkpoints: list[CheckpointResultIn] = Field(default_factory=list)
    workstation_id: Optional[str] = None
    expected_bundle_version: Optional[str] = None
    human_final_decision: Optional[str] = None
    human_decided_by: Optional[str] = None
    human_decision_comment: str = ""
    cloud_recognition: list[dict[str, Any]] = Field(default_factory=list)
    client_timing: dict[str, Any] = Field(default_factory=dict)


class HumanDecisionBody(BaseModel):
    tenant_id: str = "default"
    decision: str
    decided_by: str
    comment: str = ""


def _verdict_view(v) -> dict:
    return {
        "submission_id": v.submission_id,
        "server_overall_result": v.server_overall_result,
        "pad_overall_result": v.pad_overall_result,
        "agrees": v.agrees,
        "review_required": v.review_required,
        "rule_applied": v.rule_applied,
        "standard_revision_id": v.standard_revision_id,
        "bundle_version": v.bundle_version,
        "missing_checkpoints": v.missing_checkpoints_json or [],
        "failing_checkpoints": v.failing_checkpoints_json or [],
        "warnings": v.warnings_json or [],
        "differences": v.differences_json or [],
        "human_final_decision": v.human_final_decision,
        "human_decided_by": v.human_decided_by,
        "human_decision_comment": v.human_decision_comment,
        "recomputed_at": v.recomputed_at.isoformat() if v.recomputed_at else None,
    }


@router.post("/api/qc/results/submissions", status_code=201)
def submit_verdict(
    body: SubmitVerdictBody,
    request: Request,
    db: Session = Depends(get_db_dep),
):
    if bool(body.human_final_decision) != bool(body.human_decided_by):
        raise HTTPException(status_code=400, detail="human decision and identity are both required")
    human_actor = (
        effective_actor(request, body.human_decided_by)
        if body.human_final_decision
        else None
    )
    raw_body = body.model_dump()
    if human_actor:
        raw_body["human_decided_by"] = human_actor
    try:
        _, verdict_model, _ = service.ingest_submission(
            db,
            tenant_id=body.tenant_id,
            job_ref=body.job_ref,
            standard_revision_id=body.standard_revision_id,
            bundle_version=body.bundle_version,
            pad_overall_result=body.pad_overall_result,
            checkpoints=[(c.checkpoint_id, c.result) for c in body.checkpoints],
            workstation_id=body.workstation_id,
            expected_bundle_version=body.expected_bundle_version,
            raw=raw_body,
        )
    except ValueError as exc:
        if str(exc) == "idempotency_conflict":
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise
    if body.human_final_decision:
        if verdict_model.human_final_decision is None:
            verdict_model = service.record_human_decision(
                db,
                tenant_id=body.tenant_id,
                submission_id=verdict_model.submission_id,
                decision=body.human_final_decision,
                decided_by=human_actor or "",
                comment=body.human_decision_comment,
            )
        elif (
            verdict_model.human_final_decision != body.human_final_decision
            or verdict_model.human_decided_by != human_actor
        ):
            raise HTTPException(status_code=409, detail="idempotency_conflict")
    return _verdict_view(verdict_model)


@router.get("/api/qc/results")
def api_list_results(tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    return [_verdict_view(v) for v in service.list_results(db, tenant_id)]


@router.get("/api/qc/results/{submission_id}")
def api_get_result(submission_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        return _verdict_view(service.get_result(db, tenant_id, submission_id))
    except SubmissionNotFound:
        raise HTTPException(status_code=404, detail="result_not_found")


@router.post("/api/qc/results/{submission_id}/final-decision", status_code=201)
def api_final_decision(
    submission_id: str,
    body: HumanDecisionBody,
    request: Request,
    db: Session = Depends(get_db_dep),
):
    actor = effective_actor(request, body.decided_by)
    try:
        verdict = service.record_human_decision(
            db,
            tenant_id=body.tenant_id,
            submission_id=submission_id,
            decision=body.decision,
            decided_by=actor,
            comment=body.comment,
        )
    except SubmissionNotFound:
        raise HTTPException(status_code=404, detail="result_not_found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _verdict_view(verdict)


@router.get("/admin/results", response_class=HTMLResponse)
def admin_results(request: Request, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    results = [_verdict_view(v) for v in service.list_results(db, tenant_id)]
    return templates.TemplateResponse(
        request, "qc_results_panel.html", {"tenant_id": tenant_id, "results": results}
    )


@router.post("/admin/results/{submission_id}/final-decision")
def ui_final_decision(
    submission_id: str,
    request: Request,
    decision: str = Form(...),
    comment: str = Form(""),
    tenant_id: str = Form("default"),
    db: Session = Depends(get_db_dep),
):
    actor = effective_actor(request)
    try:
        service.record_human_decision(
            db,
            tenant_id=tenant_id,
            submission_id=submission_id,
            decision=decision,
            decided_by=actor,
            comment=comment,
        )
    except SubmissionNotFound:
        raise HTTPException(status_code=404, detail="result_not_found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(url=f"/admin/results?tenant_id={tenant_id}", status_code=303)
