"""Server-rendered Configuration / Digital Inspector Training UI.

Extends the /admin surface (behind the same admin/engineer session as Sample
Admin) with the two training flows:

* **Sample Intake** — register the raw inspection requirement text for a SKU.
* **Digital Inspector Training** — extract candidate detection points, let an
  engineer review/edit them, and confirm to activate a new standard revision.

Nothing becomes active without explicit human confirmation: an unconfirmed
intake is inactive. "Training" here is configuration, not weight fine-tuning.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.api.admin_auth import AdminSession, current_admin, require_admin_session
from src.api.deps import get_db_dep
from src.config_ui.service import (
    candidate_checkpoints,
    compute_training_status,
    list_intakes,
    list_revisions,
    list_training_dashboard,
)
from src.db.intake_models import QCStandardIntake
from src.db.sku_models import QCSkuItem
from src.intake.service import (
    confirm_standard_intake,
    create_standard_intake,
    extract_standard_draft,
    reject_standard_intake,
)

router = APIRouter(prefix="/admin", tags=["admin-config"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_LOGIN_REDIRECT = "/admin/login"


def _redirect_login() -> RedirectResponse:
    return RedirectResponse(url=_LOGIN_REDIRECT, status_code=303)


def _load_sku_or_404(db: Session, sku_id: str, tenant_id: str) -> QCSkuItem:
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    return sku


def _load_intake_or_404(
    db: Session, intake_id: str, tenant_id: str
) -> QCStandardIntake:
    intake = (
        db.query(QCStandardIntake)
        .filter_by(id=intake_id, tenant_id=tenant_id)
        .first()
    )
    if not intake:
        raise HTTPException(status_code=404, detail="Intake not found")
    return intake


# ── Training status dashboard ───────────────────────────────────────────────────


@router.get("/training", response_class=HTMLResponse)
def training_dashboard(request: Request, db: Session = Depends(get_db_dep)):
    admin = current_admin(request)
    if admin is None:
        return _redirect_login()
    statuses = list_training_dashboard(db, admin.tenant_id)
    trained_count = sum(1 for s in statuses if s.trained)
    return templates.TemplateResponse(
        request,
        "training_dashboard.html",
        context={
            "admin": admin,
            "statuses": statuses,
            "trained_count": trained_count,
            "total_count": len(statuses),
        },
    )


# ── Sample Intake: raw requirement text ─────────────────────────────────────────


@router.get("/samples/{sku_id}/intakes", response_class=HTMLResponse)
def sku_intakes(sku_id: str, request: Request, db: Session = Depends(get_db_dep)):
    admin = current_admin(request)
    if admin is None:
        return _redirect_login()
    sku = _load_sku_or_404(db, sku_id, admin.tenant_id)
    return templates.TemplateResponse(
        request,
        "sku_intakes.html",
        context={
            "admin": admin,
            "sku": sku,
            "intakes": list_intakes(db, sku_id, admin.tenant_id),
            "status": compute_training_status(db, sku),
            "revisions": list_revisions(db, sku_id, admin.tenant_id),
        },
    )


@router.post("/samples/{sku_id}/intakes", response_class=HTMLResponse)
def create_sku_intake(
    sku_id: str,
    request: Request,
    raw_text: str = Form(...),
    source_channel: Optional[str] = Form(default=None),
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    _load_sku_or_404(db, sku_id, admin.tenant_id)
    try:
        intake = create_standard_intake(
            db,
            sku_id=sku_id,
            tenant_id=admin.tenant_id,
            raw_text=raw_text,
            source_type="admin_ui",
            source_channel=source_channel,
            operator_id=str(admin.operator_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(url=f"/admin/intakes/{intake.id}", status_code=303)


# ── Digital Inspector Training workbench ────────────────────────────────────────


@router.get("/intakes/{intake_id}", response_class=HTMLResponse)
def intake_workbench(
    intake_id: str, request: Request, db: Session = Depends(get_db_dep)
):
    admin = current_admin(request)
    if admin is None:
        return _redirect_login()
    intake = _load_intake_or_404(db, intake_id, admin.tenant_id)
    sku = _load_sku_or_404(db, intake.sku_id, admin.tenant_id)
    return templates.TemplateResponse(
        request,
        "intake_workbench.html",
        context={
            "admin": admin,
            "intake": intake,
            "sku": sku,
            "candidates": candidate_checkpoints(intake),
        },
    )


@router.post("/intakes/{intake_id}/extract", response_class=HTMLResponse)
def workbench_extract(
    intake_id: str,
    request: Request,
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    _load_intake_or_404(db, intake_id, admin.tenant_id)
    try:
        extract_standard_draft(db, intake_id)
    except ValueError as exc:
        # Fail-closed: provider/parse failure leaves intake extractable with a
        # visible error; never auto-confirm.
        intake = _load_intake_or_404(db, intake_id, admin.tenant_id)
        sku = _load_sku_or_404(db, intake.sku_id, admin.tenant_id)
        return templates.TemplateResponse(
            request,
            "intake_workbench.html",
            context={
                "admin": admin,
                "intake": intake,
                "sku": sku,
                "candidates": candidate_checkpoints(intake),
                "error": f"Extraction failed: {exc}",
            },
            status_code=400,
        )
    return RedirectResponse(url=f"/admin/intakes/{intake_id}", status_code=303)


@router.post("/intakes/{intake_id}/confirm", response_class=HTMLResponse)
def workbench_confirm(
    intake_id: str,
    request: Request,
    point_code: List[str] = Form(default=[]),
    label: List[str] = Form(default=[]),
    severity: List[str] = Form(default=[]),
    pass_criteria: List[str] = Form(default=[]),
    description: List[str] = Form(default=[]),
    # Extracted semantics carried through the review form as hidden fields so a
    # counting/tolerance rule (e.g. expected_value="3", method_hint="count") is
    # not silently dropped on confirm.
    method_hint: List[str] = Form(default=[]),
    expected_value: List[str] = Form(default=[]),
    operator_comment: Optional[str] = Form(default=None),
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    intake = _load_intake_or_404(db, intake_id, admin.tenant_id)
    sku = _load_sku_or_404(db, intake.sku_id, admin.tenant_id)

    checkpoints = []
    for i, code in enumerate(point_code):
        code = (code or "").strip()
        if not code:
            continue  # unconfirmed / removed rows are skipped

        def _at(seq: List[str]) -> Optional[str]:
            return seq[i] if i < len(seq) else None

        def _clean(seq: List[str]) -> Optional[str]:
            v = _at(seq)
            v = v.strip() if isinstance(v, str) else v
            return v or None

        checkpoints.append(
            {
                "point_code": code,
                "label": (_at(label) or code).strip(),
                "severity": (_at(severity) or "major").strip() or "major",
                "pass_criteria": _clean(pass_criteria),
                "description": _clean(description),
                # Preserve extracted semantics through confirm (Codex P1).
                "method_hint": _clean(method_hint),
                "expected_value": _clean(expected_value),
            }
        )

    if not checkpoints:
        return templates.TemplateResponse(
            request,
            "intake_workbench.html",
            context={
                "admin": admin,
                "intake": intake,
                "sku": sku,
                "candidates": candidate_checkpoints(intake),
                "error": "At least one detection point is required to confirm.",
            },
            status_code=400,
        )

    try:
        revision, _conf = confirm_standard_intake(
            db,
            intake_id=intake_id,
            confirmed_by=str(admin.operator_id),
            confirmed_checkpoints=checkpoints,
            operator_comment=operator_comment,
            tenant_id=admin.tenant_id,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "intake_workbench.html",
            context={
                "admin": admin,
                "intake": intake,
                "sku": sku,
                "candidates": candidate_checkpoints(intake),
                "error": f"Confirmation failed: {exc}",
            },
            status_code=400,
        )
    return RedirectResponse(url=f"/admin/samples/{sku.id}/intakes", status_code=303)


@router.post("/intakes/{intake_id}/reject", response_class=HTMLResponse)
def workbench_reject(
    intake_id: str,
    request: Request,
    reason: Optional[str] = Form(default=None),
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    intake = _load_intake_or_404(db, intake_id, admin.tenant_id)
    try:
        reject_standard_intake(
            db,
            intake_id=intake_id,
            rejected_by=str(admin.operator_id),
            reason=reason,
            tenant_id=admin.tenant_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(
        url=f"/admin/samples/{intake.sku_id}/intakes", status_code=303
    )
