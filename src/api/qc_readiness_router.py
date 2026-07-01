"""API + UI for the Training Pack readiness gate (PR 24 §5, §6)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.qc_model.readiness.evaluator import evaluate_readiness
from src.qc_model.readiness.gate import gate_transition
from src.qc_model.readiness.waiver import WaiverValidationError, create_waiver, list_waivers

router = APIRouter(tags=["qc-readiness"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class WaiverBody(BaseModel):
    item_key: str = ""
    reason: str = ""
    supervisor_id: str = ""
    tenant_id: str = "default"


class TransitionBody(BaseModel):
    target_status: str
    tenant_id: str = "default"


@router.get("/api/qc/training-packs/{training_pack_id}/readiness")
def get_readiness(training_pack_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    return evaluate_readiness(db, training_pack_id, tenant_id).to_dict()


@router.post("/api/qc/training-packs/{training_pack_id}/status-transition")
def check_transition(training_pack_id: str, body: TransitionBody, db: Session = Depends(get_db_dep)):
    decision = gate_transition(db, training_pack_id, body.target_status, body.tenant_id)
    return {
        "training_pack_id": training_pack_id,
        "target_status": decision.target_status,
        "allowed": decision.allowed,
        "reason": decision.reason,
        "readiness": decision.readiness.to_dict(),
    }


@router.post("/api/qc/training-packs/{training_pack_id}/readiness-waivers", status_code=201)
def add_waiver(training_pack_id: str, body: WaiverBody, db: Session = Depends(get_db_dep)):
    try:
        waiver = create_waiver(
            db, training_pack_id, item_key=body.item_key, reason=body.reason,
            supervisor_id=body.supervisor_id, tenant_id=body.tenant_id,
        )
    except WaiverValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "waiver_id": waiver.id, "training_pack_id": waiver.training_pack_id,
        "check_id": waiver.check_id, "item_key": waiver.item_key,
        "supervisor_id": waiver.supervisor_id, "reason": waiver.reason,
    }


@router.get("/api/qc/training-packs/{training_pack_id}/readiness-waivers")
def get_waivers(training_pack_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    waivers = list_waivers(db, training_pack_id, tenant_id)
    return {
        "training_pack_id": training_pack_id,
        "waivers": [
            {"waiver_id": w.id, "check_id": w.check_id, "item_key": w.item_key,
             "supervisor_id": w.supervisor_id, "reason": w.reason}
            for w in waivers
        ],
    }


# ── UI ────────────────────────────────────────────────────────────────────


@router.get("/admin/qc-model/training-packs/{training_pack_id}/readiness", response_class=HTMLResponse)
def readiness_panel(request: Request, training_pack_id: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    result = evaluate_readiness(db, training_pack_id, tenant_id)
    from src.qc_model.readiness.evaluator import C_QUESTIONS
    return templates.TemplateResponse(
        request, "qc_readiness_panel.html",
        context={
            "training_pack_id": training_pack_id, "tenant_id": tenant_id,
            "result": result.to_dict(), "questions_check_id": C_QUESTIONS,
            "waivers": [
                {"item_key": w.item_key, "supervisor_id": w.supervisor_id, "reason": w.reason}
                for w in list_waivers(db, training_pack_id, tenant_id)
            ],
        },
    )


@router.post("/admin/qc-model/training-packs/{training_pack_id}/readiness-waivers")
def ui_add_waiver(
    training_pack_id: str,
    item_key: str = Form(...),
    reason: str = Form(...),
    supervisor_id: str = Form("qc_supervisor"),
    tenant_id: str = Form("default"),
    db: Session = Depends(get_db_dep),
):
    try:
        create_waiver(
            db, training_pack_id, item_key=item_key, reason=reason,
            supervisor_id=supervisor_id, tenant_id=tenant_id,
        )
    except WaiverValidationError:
        pass
    suffix = f"?tenant_id={tenant_id}" if tenant_id and tenant_id != "default" else ""
    return RedirectResponse(
        url=f"/admin/qc-model/training-packs/{training_pack_id}/readiness{suffix}", status_code=303
    )
