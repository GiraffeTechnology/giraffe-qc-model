"""FastAPI admin router for the shared QC Sample Admin UI.

Routes are at /admin/samples and are shared by Pad and Server editions.
Sample DB logic does not branch by edition.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.api.authz import effective_tenant
from src.api.sample_security import require_sample_admin_mutation
from src.api.uploads import validate_safe_id
from src.storage.upload_validation import (
    UploadValidationError,
    read_and_validate_upload,
)
from src.web.i18n import install_i18n, resolve_language, translate
from src.db.sku_models import (
    QCDetectionPoint,
    QCInspectionRequirement,
    QCSkuItem,
    QCStandardPhoto,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_sample_admin_mutation)],
)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_i18n(templates)

_DATA_DIR = Path(os.getenv("QC_SAMPLE_DATA_DIR", "data/qc_samples"))
_LEGACY_DATA_DIR = Path("data/qc_samples")


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _primary_photo(sku: QCSkuItem) -> Optional[QCStandardPhoto]:
    for p in sku.photos:
        if p.is_primary:
            return p
    return sku.photos[0] if sku.photos else None


def _photo_display_url(photo: QCStandardPhoto, tenant_id: str) -> Optional[str]:
    """Return a browser-safe photo URL without exposing a server path."""
    if photo.image_url:
        return photo.image_url
    if photo.local_path:
        return f"/admin/samples/photos/{photo.id}?tenant_id={quote(tenant_id, safe='')}"
    return None


def resolve_sample_photo_path(local_path: str) -> Optional[Path]:
    """Resolve old relative paths inside the configured persistent data root."""
    path = Path(local_path)
    if not path.is_absolute():
        try:
            suffix = path.relative_to(_LEGACY_DATA_DIR)
        except ValueError:
            return None
        path = _DATA_DIR / suffix
    resolved = path.resolve()
    data_root = _DATA_DIR.resolve()
    if resolved != data_root and data_root not in resolved.parents:
        return None
    return resolved


def _duplicate_item_error(request: Request, item_number: str) -> str:
    return translate("sample.error.duplicate", resolve_language(request)).format(
        item_number=item_number
    )


# GET /admin/samples
@router.get("/samples", response_class=HTMLResponse)
def list_samples(
    request: Request,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    skus = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.tenant_id == tenant_id, QCSkuItem.status == "active")
        .order_by(QCSkuItem.created_at.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "sample_list.html",
        context={"skus": skus, "tenant_id": tenant_id},
    )


# GET /admin/samples/new
@router.get("/samples/new", response_class=HTMLResponse)
def new_sample_form(request: Request, tenant_id: str = "default"):
    return templates.TemplateResponse(
        request,
        "sample_new.html",
        context={"tenant_id": tenant_id, "error": None},
    )


# POST /admin/samples
@router.post("/samples", response_class=HTMLResponse)
def create_sample(
    request: Request,
    tenant_id: str = Form(default="default"),
    item_number: str = Form(...),
    name: str = Form(...),
    category: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    db: Session = Depends(get_db_dep),
):
    existing = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.tenant_id == tenant_id, QCSkuItem.item_number == item_number)
        .first()
    )
    if existing:
        return templates.TemplateResponse(
            request,
            "sample_new.html",
            context={
                "tenant_id": tenant_id,
                "error": _duplicate_item_error(request, item_number),
                "item_number": item_number,
                "name": name,
                "category": category,
                "description": description,
            },
            status_code=409,
        )

    now = _utcnow()
    sku = QCSkuItem(
        id=_new_id(),
        tenant_id=tenant_id,
        item_number=item_number.strip(),
        name=name.strip(),
        category=category.strip() if category else None,
        description=description.strip() if description else None,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(sku)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return templates.TemplateResponse(
            request,
            "sample_new.html",
            context={
                "tenant_id": tenant_id,
                "error": _duplicate_item_error(request, item_number),
                "item_number": item_number,
                "name": name,
                "category": category,
                "description": description,
            },
            status_code=409,
        )
    return RedirectResponse(url=f"/admin/samples/{sku.id}?tenant_id={tenant_id}", status_code=303)


# GET /admin/samples/{sku_id}
@router.get("/samples/{sku_id}", response_class=HTMLResponse)
def sample_detail(
    sku_id: str,
    request: Request,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    return templates.TemplateResponse(
        request,
        "sample_detail.html",
        context={
            "sku": sku,
            "primary_photo": _primary_photo(sku),
            "tenant_id": tenant_id,
            "sample_photo_url": _photo_display_url,
        },
    )


@router.get("/samples/photos/{photo_id}")
def serve_sample_photo(
    photo_id: str,
    request: Request,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    """Serve an uploaded sample image to the authenticated owning tenant."""
    tenant_id = effective_tenant(request, tenant_id)
    validate_safe_id(photo_id, "photo_id")
    photo = (
        db.query(QCStandardPhoto)
        .filter_by(id=photo_id, tenant_id=tenant_id)
        .first()
    )
    if photo is None or not photo.local_path:
        raise HTTPException(status_code=404, detail="Photo not found")
    path = resolve_sample_photo_path(photo.local_path)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Photo file missing")
    return FileResponse(str(path), media_type=photo.mime_type or "application/octet-stream")


# POST /admin/samples/{sku_id}/photos
@router.post("/samples/{sku_id}/photos", response_class=HTMLResponse)
async def add_photo(
    sku_id: str,
    request: Request,
    tenant_id: str = Form(default="default"),
    is_primary: bool = Form(default=False),
    angle: Optional[str] = Form(default=None),
    view_type: Optional[str] = Form(default=None),
    image_url: Optional[str] = Form(default=None),
    local_path_input: Optional[str] = Form(default=None),
    photo_file: Optional[UploadFile] = File(default=None),
    db: Session = Depends(get_db_dep),
):
    # Authoritative tenant from the authenticated principal; guard the sku_id
    # since it is used to build a filesystem path.
    tenant_id = effective_tenant(request, tenant_id)
    validate_safe_id(sku_id, "sku_id")
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    now = _utcnow()
    sha256_hash: Optional[str] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    mime_type: Optional[str] = None
    saved_local_path: Optional[str] = None

    if photo_file and photo_file.filename:
        # Mode A: upload file to data/qc_samples/{tenant_id}/{sku_id}/photos/
        # Hardened: streamed size bound + magic-byte MIME sniff (fail-closed).
        try:
            validated = await read_and_validate_upload(photo_file)
        except UploadValidationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
        content = validated.content
        sha256_hash = validated.sha256
        mime_type = validated.mime_type

        try:
            import cv2
            import numpy as np
            np_arr = np.frombuffer(content, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img is not None:
                height_px, width_px = img.shape[:2]
        except Exception:
            pass

        ext = validated.extension or Path(photo_file.filename).suffix or ".jpg"
        filename = f"{_new_id()}{ext}"
        dest_dir = _DATA_DIR / tenant_id / sku_id / "photos"
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / filename).write_bytes(content)
        saved_local_path = str(dest_dir / filename)
    else:
        # Mode B: register existing URL or local path
        saved_local_path = local_path_input or None

    if is_primary:
        db.query(QCStandardPhoto).filter(
            QCStandardPhoto.sku_id == sku_id,
            QCStandardPhoto.tenant_id == tenant_id,
        ).update({"is_primary": False})

    photo = QCStandardPhoto(
        id=_new_id(),
        tenant_id=tenant_id,
        sku_id=sku_id,
        image_url=image_url or None,
        local_path=saved_local_path,
        angle=angle or None,
        view_type=view_type or None,
        sha256=sha256_hash,
        width_px=width_px,
        height_px=height_px,
        mime_type=mime_type,
        is_primary=is_primary,
        created_at=now,
        updated_at=now,
    )
    db.add(photo)
    db.commit()
    return RedirectResponse(url=f"/admin/samples/{sku_id}?tenant_id={tenant_id}", status_code=303)


# POST /admin/samples/{sku_id}/photos/{photo_id}/set-primary
@router.post("/samples/{sku_id}/photos/{photo_id}/set-primary", response_class=HTMLResponse)
def set_primary_photo(
    sku_id: str,
    photo_id: str,
    request: Request,
    tenant_id: str = Form(default="default"),
    db: Session = Depends(get_db_dep),
):
    db.query(QCStandardPhoto).filter(
        QCStandardPhoto.sku_id == sku_id,
        QCStandardPhoto.tenant_id == tenant_id,
    ).update({"is_primary": False})

    photo = (
        db.query(QCStandardPhoto)
        .filter(
            QCStandardPhoto.id == photo_id,
            QCStandardPhoto.sku_id == sku_id,
            QCStandardPhoto.tenant_id == tenant_id,
        )
        .first()
    )
    if photo:
        photo.is_primary = True
    db.commit()
    return RedirectResponse(url=f"/admin/samples/{sku_id}?tenant_id={tenant_id}", status_code=303)


# POST /admin/samples/{sku_id}/requirements
@router.post("/samples/{sku_id}/requirements", response_class=HTMLResponse)
def add_requirement(
    sku_id: str,
    request: Request,
    tenant_id: str = Form(default="default"),
    code: str = Form(...),
    title: str = Form(...),
    requirement_text: str = Form(...),
    severity: str = Form(default="major"),
    pass_criteria: Optional[str] = Form(default=None),
    sort_order: int = Form(default=0),
    db: Session = Depends(get_db_dep),
):
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    now = _utcnow()
    req = QCInspectionRequirement(
        id=_new_id(),
        tenant_id=tenant_id,
        sku_id=sku_id,
        code=code.strip(),
        title=title.strip(),
        requirement_text=requirement_text.strip(),
        severity=severity,
        pass_criteria=pass_criteria.strip() if pass_criteria else None,
        sort_order=sort_order,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(req)
    db.commit()
    return RedirectResponse(url=f"/admin/samples/{sku_id}?tenant_id={tenant_id}", status_code=303)


# POST /admin/samples/{sku_id}/detection-points
@router.post("/samples/{sku_id}/detection-points", response_class=HTMLResponse)
def add_detection_point(
    sku_id: str,
    request: Request,
    tenant_id: str = Form(default="default"),
    point_code: str = Form(...),
    label: str = Form(...),
    description: Optional[str] = Form(default=None),
    roi_json_text: Optional[str] = Form(default=None),
    severity: str = Form(default="major"),
    sort_order: int = Form(default=0),
    db: Session = Depends(get_db_dep),
):
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    roi = None
    if roi_json_text and roi_json_text.strip():
        try:
            roi = json.loads(roi_json_text.strip())
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid ROI JSON: {exc}")

    now = _utcnow()
    dp = QCDetectionPoint(
        id=_new_id(),
        tenant_id=tenant_id,
        sku_id=sku_id,
        point_code=point_code.strip(),
        label=label.strip(),
        description=description.strip() if description else None,
        roi_json=roi,
        severity=severity,
        sort_order=sort_order,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(dp)
    db.commit()
    return RedirectResponse(url=f"/admin/samples/{sku_id}?tenant_id={tenant_id}", status_code=303)


# POST /admin/samples/{sku_id}/archive
@router.post("/samples/{sku_id}/archive", response_class=HTMLResponse)
def archive_sample(
    sku_id: str,
    request: Request,
    tenant_id: str = Form(default="default"),
    db: Session = Depends(get_db_dep),
):
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    sku.status = "archived"
    db.commit()
    return RedirectResponse(url="/admin/samples", status_code=303)
