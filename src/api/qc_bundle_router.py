"""API + admin UI for bundle management and workstation management (§6, §7).

Owns ``/admin/bundles`` and ``/admin/workstations`` plus their JSON handlers.
Does not own the publish/build action (S2 studio) — bundles arrive here already
signed via ``POST /api/qc/bundles`` and are re-verified fail-closed on download
and assignment.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.qc_model.bundle import service
from src.qc_model.bundle.manifest import BundleVerificationError, SignedBundle
from src.qc_model.bundle.service import BundleNotFound, WorkstationNotFound
from src.web.i18n import install_i18n

router = APIRouter(tags=["qc-bundles"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
# Carry the shared web-shell language switch on the bundle/workstation pages.
install_i18n(templates)


# ── request bodies ────────────────────────────────────────────────────────────


class RecordBundleBody(BaseModel):
    tenant_id: str = "default"
    manifest: dict
    signature: str
    signature_algo: str = "ed25519"
    manifest_sha256: str = ""
    created_by: str = ""


class RegisterWorkstationBody(BaseModel):
    tenant_id: str = "default"
    workstation_id: str
    display_name: str
    site_or_line: Optional[str] = None


class AssignBundleBody(BaseModel):
    tenant_id: str = "default"
    bundle_pk: str
    assigned_by: str = ""


class PadReportBody(BaseModel):
    tenant_id: str = "default"
    installed_bundle_version: Optional[str] = None
    sync_status: Optional[str] = None
    error: Optional[str] = None
    outbox_upload_status: Optional[str] = None


# ── views ─────────────────────────────────────────────────────────────────────


def _bundle_view(b) -> dict:
    return {
        "id": b.id,
        "bundle_version": b.bundle_version,
        "status": b.status,
        "sku_count": b.sku_count,
        "standard_revision_count": b.standard_revision_count,
        "created_by": b.created_by,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "manifest_sha256": b.manifest_sha256,
        "signature_algo": b.signature_algo,
        "signed": bool(b.signature),
    }


def _workstation_view(w) -> dict:
    return {
        "id": w.id,
        "workstation_id": w.workstation_id,
        "display_name": w.display_name,
        "site_or_line": w.site_or_line,
        "paired_status": w.paired_status,
        "assigned_bundle_version": w.assigned_bundle_version,
        "installed_bundle_version": w.installed_bundle_version,
        "last_seen_at": w.last_seen_at.isoformat() if w.last_seen_at else None,
        "last_sync_status": w.last_sync_status,
        "last_error": w.last_error,
        "outbox_upload_status": w.outbox_upload_status,
        "pairing_token": w.pairing_token,
        # convenience: does the installed version match what was assigned?
        "in_sync": (
            w.assigned_bundle_version is not None
            and w.assigned_bundle_version == w.installed_bundle_version
        ),
    }


# ── bundle JSON API ───────────────────────────────────────────────────────────


@router.post("/api/qc/bundles", status_code=201)
def record_bundle(body: RecordBundleBody, db: Session = Depends(get_db_dep)):
    signed = SignedBundle(
        manifest=body.manifest,
        signature=body.signature,
        signature_algo=body.signature_algo,
        manifest_sha256=body.manifest_sha256,
    )
    try:
        bundle = service.record_signed_bundle(
            db, tenant_id=body.tenant_id, signed=signed, created_by=body.created_by
        )
    except BundleVerificationError as exc:
        raise HTTPException(status_code=400, detail={"reason": exc.reason, "detail": exc.detail})
    return _bundle_view(bundle)


@router.get("/api/qc/bundles")
def api_list_bundles(tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    return [_bundle_view(b) for b in service.list_bundles(db, tenant_id)]


@router.get("/api/qc/bundles/{bundle_pk}")
def api_get_bundle(bundle_pk: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        return _bundle_view(service.get_bundle(db, tenant_id, bundle_pk))
    except BundleNotFound:
        raise HTTPException(status_code=404, detail="bundle_not_found")


@router.get("/api/qc/bundles/{bundle_pk}/download")
def api_download_bundle(bundle_pk: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    """Download the signed bundle. Fail-closed: tampered bundles are rejected."""
    try:
        signed = service.download_bundle(db, tenant_id, bundle_pk)
    except BundleNotFound:
        raise HTTPException(status_code=404, detail="bundle_not_found")
    except BundleVerificationError as exc:
        # Verification failure must not yield the payload.
        raise HTTPException(status_code=409, detail={"reason": exc.reason, "detail": exc.detail})
    return JSONResponse(
        {
            "manifest": signed.manifest,
            "signature": signed.signature,
            "signature_algo": signed.signature_algo,
            "manifest_sha256": signed.manifest_sha256,
        }
    )


# ── workstation JSON API ──────────────────────────────────────────────────────


@router.post("/api/qc/workstations", status_code=201)
def api_register_workstation(body: RegisterWorkstationBody, db: Session = Depends(get_db_dep)):
    ws = service.register_workstation(
        db,
        tenant_id=body.tenant_id,
        workstation_id=body.workstation_id,
        display_name=body.display_name,
        site_or_line=body.site_or_line,
    )
    return _workstation_view(ws)


@router.get("/api/qc/workstations")
def api_list_workstations(tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    return [_workstation_view(w) for w in service.list_workstations(db, tenant_id)]


@router.get("/api/qc/workstations/{workstation_pk}")
def api_get_workstation(workstation_pk: str, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    try:
        return _workstation_view(service.get_workstation(db, tenant_id, workstation_pk))
    except WorkstationNotFound:
        raise HTTPException(status_code=404, detail="workstation_not_found")


@router.post("/api/qc/workstations/{workstation_pk}/assign", status_code=201)
def api_assign_bundle(workstation_pk: str, body: AssignBundleBody, db: Session = Depends(get_db_dep)):
    try:
        ws = service.assign_bundle(
            db,
            tenant_id=body.tenant_id,
            workstation_pk=workstation_pk,
            bundle_pk=body.bundle_pk,
            assigned_by=body.assigned_by,
        )
    except (WorkstationNotFound, BundleNotFound):
        raise HTTPException(status_code=404, detail="not_found")
    except BundleVerificationError as exc:
        raise HTTPException(status_code=409, detail={"reason": exc.reason, "detail": exc.detail})
    return _workstation_view(ws)


@router.post("/api/qc/workstations/{workstation_pk}/report", status_code=200)
def api_pad_report(workstation_pk: str, body: PadReportBody, db: Session = Depends(get_db_dep)):
    """Simulated Pad import/report path — updates installed version + sync state."""
    try:
        ws = service.report_from_pad(
            db,
            tenant_id=body.tenant_id,
            workstation_pk=workstation_pk,
            installed_bundle_version=body.installed_bundle_version,
            sync_status=body.sync_status,
            error=body.error,
            outbox_upload_status=body.outbox_upload_status,
        )
    except WorkstationNotFound:
        raise HTTPException(status_code=404, detail="workstation_not_found")
    return _workstation_view(ws)


# ── admin UI ──────────────────────────────────────────────────────────────────


@router.get("/admin/bundles", response_class=HTMLResponse)
def admin_bundles(request: Request, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    bundles = [_bundle_view(b) for b in service.list_bundles(db, tenant_id)]
    workstations = [_workstation_view(w) for w in service.list_workstations(db, tenant_id)]
    return templates.TemplateResponse(
        request,
        "qc_bundles_panel.html",
        {"tenant_id": tenant_id, "bundles": bundles, "workstations": workstations},
    )


@router.get("/admin/workstations", response_class=HTMLResponse)
def admin_workstations(request: Request, tenant_id: str = "default", db: Session = Depends(get_db_dep)):
    workstations = [_workstation_view(w) for w in service.list_workstations(db, tenant_id)]
    bundles = [_bundle_view(b) for b in service.list_bundles(db, tenant_id)]
    return templates.TemplateResponse(
        request,
        "qc_workstations_panel.html",
        {"tenant_id": tenant_id, "workstations": workstations, "bundles": bundles},
    )


@router.post("/admin/workstations/register")
def ui_register_workstation(
    workstation_id: str = Form(...),
    display_name: str = Form(...),
    site_or_line: str = Form(""),
    tenant_id: str = Form("default"),
    db: Session = Depends(get_db_dep),
):
    service.register_workstation(
        db,
        tenant_id=tenant_id,
        workstation_id=workstation_id,
        display_name=display_name,
        site_or_line=site_or_line or None,
    )
    return RedirectResponse(url=f"/admin/workstations?tenant_id={tenant_id}", status_code=303)


@router.post("/admin/workstations/{workstation_pk}/assign")
def ui_assign_bundle(
    workstation_pk: str,
    bundle_pk: str = Form(...),
    tenant_id: str = Form("default"),
    assigned_by: str = Form(""),
    db: Session = Depends(get_db_dep),
):
    try:
        service.assign_bundle(
            db,
            tenant_id=tenant_id,
            workstation_pk=workstation_pk,
            bundle_pk=bundle_pk,
            assigned_by=assigned_by,
        )
    except (WorkstationNotFound, BundleNotFound):
        raise HTTPException(status_code=404, detail="not_found")
    except BundleVerificationError as exc:
        raise HTTPException(status_code=409, detail={"reason": exc.reason})
    return RedirectResponse(url=f"/admin/workstations?tenant_id={tenant_id}", status_code=303)
