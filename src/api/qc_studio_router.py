"""Admin Studio router — chat-first SKU + standard training (S2, PRD §5.1–§5.6).

Mounts the three-panel ``/admin/studio`` page and its backend routes:

* ``GET  /admin/studio``                     — three-panel Studio page
* ``GET  /admin/studio/skus``                — SKU list / search / status filter
* ``GET  /admin/studio/skus/{sku_id}``       — SKU card (right panel)
* ``POST /admin/studio/chat``                — conversational SKU create + extract
* ``POST /admin/studio/upload``              — hardened standard-photo upload
* ``GET  /admin/studio/photos/{photo_id}``   — serve a stored standard photo
* ``POST /admin/studio/confirm``             — confirm / reject detection points
* ``POST /admin/studio/publish``             — publish signed L2 bundle
* ``GET  /admin/studio/bundles/{bundle_id}/download`` — download signed .tar.gz (re-verified)
* ``GET  /admin/studio/skus/{sku_id}/bundles`` — bundle history (S3 owns the UI)

Extraction, confirmation and upload validation are reused from existing
hardened modules — this router only wires them to the chat surface.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.db.sku_models import QCSkuItem, QCStandardPhoto
from src.db.studio_models import QCPublishBundle
from src.intake.service import confirm_standard_intake, reject_standard_intake
from src.qc_model.studio import service as studio
from src.storage.upload_validation import (
    UploadValidationError,
    read_and_validate_upload,
)
from src.api.authz import effective_tenant
from src.api.uploads import validate_safe_id
from src.web.i18n import install_i18n

router = APIRouter(tags=["admin-studio"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
# Carry the shared web-shell language switch on the Studio page (S1 seam).
install_i18n(templates)

_STUDIO_DATA_DIR = Path("data/qc_studio")


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Page ──────────────────────────────────────────────────────────────────────


@router.get("/admin/studio", response_class=HTMLResponse)
def studio_page(request: Request, tenant_id: str = "default"):
    return templates.TemplateResponse(
        request, "admin_studio.html", {"tenant_id": tenant_id}
    )


# ── SKU list / search / status filter (left panel) ────────────────────────────


@router.get("/admin/studio/skus")
def list_skus(
    q: str = "",
    status: str = "",
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    query = db.query(QCSkuItem).filter(QCSkuItem.tenant_id == tenant_id)
    if status:
        query = query.filter(QCSkuItem.status == status)
    skus = query.order_by(QCSkuItem.updated_at.desc()).all()

    needle = q.strip().lower()
    items: List[Dict[str, Any]] = []
    for sku in skus:
        if needle and needle not in sku.item_number.lower() and needle not in sku.name.lower():
            continue
        items.append(studio.sku_summary(db, sku))
    return {"items": items}


@router.get("/admin/studio/skus/{sku_id}")
def get_sku(
    sku_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    sku = db.query(QCSkuItem).filter_by(id=sku_id, tenant_id=tenant_id).first()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    return studio.sku_summary(db, sku)


# ── Chat (center panel) ───────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    tenant_id: str = "default"
    message: str
    sku_id: Optional[str] = None
    operator_id: Optional[str] = None


@router.post("/admin/studio/chat")
def studio_chat(body: ChatRequest, db: Session = Depends(get_db_dep)):
    result = studio.process_studio_chat(
        db,
        tenant_id=body.tenant_id,
        message=body.message,
        current_sku_id=body.sku_id,
        operator_id=body.operator_id,
    )
    return result.to_dict()


# ── Voice toggle (§5.3) — controlled not-enabled response, never crashes ──────


@router.post("/admin/studio/voice")
def studio_voice():
    return JSONResponse(
        {"status": "not_enabled", "message": "Voice input is not enabled yet."}
    )


# ── Standard photo upload (§5.3) ──────────────────────────────────────────────


@router.post("/admin/studio/upload")
async def studio_upload(
    request: Request,
    sku_id: str = Form(...),
    tenant_id: str = Form("default"),
    view_type: Optional[str] = Form(None),
    angle: Optional[str] = Form(None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db_dep),
):
    # The multipart body is not rewritten by the auth gate, so derive the
    # authoritative tenant from the authenticated principal here.
    tenant_id = effective_tenant(request, tenant_id)
    # sku_id is used to build a filesystem path — reject traversal attempts.
    validate_safe_id(sku_id, "sku_id")
    sku = db.query(QCSkuItem).filter_by(id=sku_id, tenant_id=tenant_id).first()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")

    # Reuse the shared hardened validator (streamed size bound + MIME sniff).
    try:
        validated = await read_and_validate_upload(image)
    except UploadValidationError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)

    dest_dir = _STUDIO_DATA_DIR / tenant_id / sku_id / "photos"
    dest_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{_uid()}{validated.extension}"
    dest_path = dest_dir / filename
    dest_path.write_bytes(validated.content)

    # First photo becomes primary so the right-panel preview always resolves.
    has_existing = bool(sku.photos)
    is_primary = not has_existing
    if is_primary:
        db.query(QCStandardPhoto).filter(
            QCStandardPhoto.sku_id == sku_id,
            QCStandardPhoto.tenant_id == tenant_id,
        ).update({"is_primary": False})

    now = _now()
    photo = QCStandardPhoto(
        id=_uid(),
        tenant_id=tenant_id,
        sku_id=sku_id,
        local_path=str(dest_path),
        view_type=view_type,
        angle=angle,
        sha256=validated.sha256,
        mime_type=validated.mime_type,
        is_primary=is_primary,
        created_at=now,
        updated_at=now,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    return {
        "status": "uploaded",
        "photo_id": photo.id,
        "url": studio.photo_url(photo),
        "mime_type": validated.mime_type,
        "size_bytes": validated.size_bytes,
        "sha256": validated.sha256,
        "sku": studio.sku_summary(db, sku),
    }


@router.get("/admin/studio/photos/{photo_id}")
def serve_photo(
    photo_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    photo = db.query(QCStandardPhoto).filter_by(id=photo_id, tenant_id=tenant_id).first()
    if photo is None or not photo.local_path:
        raise HTTPException(status_code=404, detail="Photo not found")
    path = Path(photo.local_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Photo file missing")
    return FileResponse(str(path), media_type=photo.mime_type or "application/octet-stream")


# ── Confirm / reject detection points (§5.5) ──────────────────────────────────


class ConfirmCheckpoint(BaseModel):
    point_code: str
    label: str
    description: Optional[str] = None
    method_hint: Optional[str] = None
    severity: str = "major"
    expected_value: Optional[str] = None
    pass_criteria: Optional[str] = None


class ConfirmRequest(BaseModel):
    tenant_id: str = "default"
    intake_id: str
    confirmed_by: str = "qc_supervisor"
    checkpoints: List[ConfirmCheckpoint]
    operator_comment: Optional[str] = None


@router.post("/admin/studio/confirm")
def studio_confirm(body: ConfirmRequest, db: Session = Depends(get_db_dep)):
    checkpoints = [cp.model_dump() for cp in body.checkpoints]

    # Fail closed: a counting checkpoint with no expected value must not be
    # confirmed — counts are never guessed (§5.4).
    for cp in checkpoints:
        if cp.get("method_hint") == "counting" and not (cp.get("expected_value") or "").strip():
            return JSONResponse(
                {
                    "error": (
                        f"Detection point {cp['point_code']} needs an expected "
                        f"count before it can be confirmed."
                    )
                },
                status_code=400,
            )

    try:
        revision, conf = confirm_standard_intake(
            db,
            intake_id=body.intake_id,
            confirmed_by=body.confirmed_by,
            confirmed_checkpoints=checkpoints,
            operator_comment=body.operator_comment,
            tenant_id=body.tenant_id,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    sku = db.query(QCSkuItem).filter_by(id=revision.sku_id, tenant_id=body.tenant_id).first()
    return {
        "status": "confirmed",
        "revision_id": revision.id,
        "revision_no": revision.revision_no,
        "confirmation_id": conf.id,
        "confirmed_by": conf.confirmed_by,
        "sku": studio.sku_summary(db, sku) if sku else None,
    }


class RejectRequest(BaseModel):
    tenant_id: str = "default"
    intake_id: str
    rejected_by: str = "qc_supervisor"
    reason: Optional[str] = None


@router.post("/admin/studio/reject")
def studio_reject(body: RejectRequest, db: Session = Depends(get_db_dep)):
    try:
        intake = reject_standard_intake(
            db,
            intake_id=body.intake_id,
            rejected_by=body.rejected_by,
            reason=body.reason,
            tenant_id=body.tenant_id,
        )
    except Exception as exc:  # noqa: BLE001 - surface as 400
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"status": intake.status, "intake_id": intake.id}


# ── Publish signed L2 bundle (§5.6) ───────────────────────────────────────────


class PublishRequest(BaseModel):
    tenant_id: str = "default"
    sku_id: str
    published_by: Optional[str] = "qc_supervisor"


@router.post("/admin/studio/publish")
def studio_publish(body: PublishRequest, db: Session = Depends(get_db_dep)):
    try:
        bundle = studio.publish_bundle(
            db,
            sku_id=body.sku_id,
            tenant_id=body.tenant_id,
            published_by=body.published_by,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"status": "published", "bundle": studio.bundle_view(bundle)}


@router.get("/admin/studio/bundles/{bundle_id}/download")
def download_bundle(
    bundle_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    """Serve the canonical signed ``.tar.gz`` for a published bundle (re-verified).

    Fail-closed: a tenant-foreign or unknown bundle is 404; a missing on-disk
    payload or an archive that no longer verifies is 409 (the bytes never leave).
    """
    try:
        archive_bytes, bundle = studio.download_publish_bundle(db, tenant_id, bundle_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Bundle not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    filename = f"{bundle.sku_id}-r{bundle.revision_no}-{bundle.id}.tar.gz"
    return Response(
        content=archive_bytes,
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/admin/studio/skus/{sku_id}/bundles")
def list_bundles(
    sku_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    bundles = (
        db.query(QCPublishBundle)
        .filter_by(sku_id=sku_id, tenant_id=tenant_id)
        .order_by(QCPublishBundle.created_at.desc())
        .all()
    )
    return {"bundles": [studio.bundle_view(b) for b in bundles]}
