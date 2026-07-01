"""API + UI for the Phase 1 visual QC training engine.

This router *extends* the existing admin UI (it does not replace it). It adds:
- ``GET  /admin/qc-model``                            — Phase 1 admin panel
- ``GET  /api/qc-model/runtime-profiles``             — dual default profiles
- ``GET  /api/qc-model/checkpoint-categories``        — categories + AI roles
- ``GET  /api/qc-model/lifecycle``                    — inspector lifecycle states
- ``GET  /api/qc/skus/{sku_id}/detection-points``     — DP + proposed/confirmed category
- ``POST /api/qc/detection-points/{id}/confirm-category`` — confirm a category
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.db.sku_models import QCDetectionPoint, QCSkuItem
from src.qc_model.classification_service import (
    classification_view,
    confirm_category,
    ensure_classification,
)
from src.qc_model.runtime_profiles import default_runtime_profiles_config
from src.qc_model.schemas.checkpoint import CheckpointCategory, default_ai_role
from src.qc_model.schemas.digital_inspector import InspectorStatus

router = APIRouter(tags=["qc-model"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ── JSON: product configuration ───────────────────────────────────────────


@router.get("/api/qc-model/runtime-profiles")
def get_runtime_profiles():
    """Return the two product-default Qwen3.5-VL runtime profiles + compat flag."""
    return default_runtime_profiles_config()


@router.get("/api/qc-model/checkpoint-categories")
def get_checkpoint_categories():
    """Return checkpoint categories, default AI roles, and AI-primary flag."""
    return {
        "categories": [
            {
                "category": c.value,
                "default_ai_role": default_ai_role(c.value).value,
                "ai_can_be_primary_judge": c == CheckpointCategory.VISUAL_DEFECT,
            }
            for c in CheckpointCategory
        ]
    }


@router.get("/api/qc-model/lifecycle")
def get_lifecycle():
    """Return the digital inspector lifecycle states in order."""
    return {"states": [s.value for s in InspectorStatus]}


# ── JSON: detection point categories ──────────────────────────────────────


@router.get("/api/qc/skus/{sku_id}/detection-points")
def list_sku_detection_points(
    sku_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    sku = db.query(QCSkuItem).filter_by(id=sku_id, tenant_id=tenant_id).first()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    out = []
    for dp in sku.detection_points:
        classification = ensure_classification(db, dp)
        view = classification_view(classification)
        view.update(
            {
                "point_code": dp.point_code,
                "label": dp.label,
                "severity": dp.severity,
            }
        )
        out.append(view)
    return {"sku_id": sku_id, "detection_points": out}


@router.post("/api/qc/detection-points/{detection_point_id}/confirm-category")
def confirm_detection_point_category(
    detection_point_id: str,
    confirmed_category: str = Form(...),
    confirmed_by: str = Form(...),
    rationale: str = Form(""),
    db: Session = Depends(get_db_dep),
):
    try:
        classification = confirm_category(
            db,
            detection_point_id=detection_point_id,
            confirmed_category=confirmed_category,
            confirmed_by=confirmed_by,
            rationale=rationale,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return classification_view(classification)


# ── UI: Phase 1 admin panel (extends existing admin UI) ───────────────────


@router.get("/admin/qc-model", response_class=HTMLResponse)
def qc_model_panel(
    request: Request,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    skus = db.query(QCSkuItem).filter_by(tenant_id=tenant_id).all()
    sku_rows = []
    for sku in skus:
        points = []
        for dp in sku.detection_points:
            classification = ensure_classification(db, dp)
            view = classification_view(classification)
            points.append(
                {
                    "id": dp.id,
                    "point_code": dp.point_code,
                    "label": dp.label,
                    "severity": dp.severity,
                    **view,
                }
            )
        sku_rows.append({"sku": sku, "points": points})

    return templates.TemplateResponse(
        request,
        "qc_model_panel.html",
        context={
            "sku_rows": sku_rows,
            "categories": [c.value for c in CheckpointCategory],
            "runtime_profiles": default_runtime_profiles_config()["default_runtime_profiles"],
            "lifecycle_states": [s.value for s in InspectorStatus],
            "tenant_id": tenant_id,
        },
    )


@router.post("/admin/qc-model/detection-points/{detection_point_id}/confirm-category")
def ui_confirm_category(
    detection_point_id: str,
    confirmed_category: str = Form(...),
    confirmed_by: str = Form("qc_supervisor"),
    rationale: str = Form(""),
    db: Session = Depends(get_db_dep),
):
    try:
        confirm_category(
            db,
            detection_point_id=detection_point_id,
            confirmed_category=confirmed_category,
            confirmed_by=confirmed_by,
            rationale=rationale,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(url="/admin/qc-model", status_code=303)
