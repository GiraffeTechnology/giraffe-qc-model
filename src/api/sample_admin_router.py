"""FastAPI admin router for the shared QC Sample Admin UI.

Routes are at /admin and are shared by Pad and Server editions. Every route
sits behind an authenticated admin/engineer session (task A1); the tenant is
derived from the logged-in operator and never trusted from the request.
Sample DB logic does not branch by edition.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.admin_auth import (
    AdminSession,
    current_admin,
    login_admin,
    logout_admin,
    require_admin_session,
)
from src.api.deps import get_db_dep
from src.api.uploads import extension_for_mime, validate_image_upload, validate_safe_id
from src.db.sku_models import (
    QCDetectionPoint,
    QCInspectionRequirement,
    QCSkuItem,
    QCStandardPhoto,
)
from src.pad.session_service import authenticate_operator, seed_demo_operators

router = APIRouter(prefix="/admin", tags=["admin"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

_DATA_DIR = Path("data/qc_samples")

_LOGIN_REDIRECT = "/admin/login"


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _primary_photo(sku: QCSkuItem) -> Optional[QCStandardPhoto]:
    for p in sku.photos:
        if p.is_primary:
            return p
    return sku.photos[0] if sku.photos else None


def _redirect_login() -> RedirectResponse:
    return RedirectResponse(url=_LOGIN_REDIRECT, status_code=303)


# ── Authentication ─────────────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
def admin_login_page(request: Request):
    if current_admin(request) is not None:
        return RedirectResponse(url="/admin/samples", status_code=303)
    return templates.TemplateResponse(request, "admin_login.html", {"error": None})


@router.post("/login")
def admin_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    tenant_id: str = Form(default="demo"),
    db: Session = Depends(get_db_dep),
):
    # Seeding is a no-op unless test/opt-in (see seed_demo_operators_allowed).
    seed_demo_operators(db, tenant_id)
    operator = authenticate_operator(db, username, password, tenant_id)
    if operator is None or operator.role not in {"admin", "engineer"}:
        return templates.TemplateResponse(
            request,
            "admin_login.html",
            {"error": "Invalid credentials or insufficient role."},
            status_code=401,
        )
    login_admin(request, operator)
    return RedirectResponse(url="/admin/samples", status_code=303)


@router.post("/logout")
def admin_logout(request: Request):
    logout_admin(request)
    return RedirectResponse(url=_LOGIN_REDIRECT, status_code=303)


# ── Sample Intake pages ─────────────────────────────────────────────────────────


# GET /admin/samples
@router.get("/samples", response_class=HTMLResponse)
def list_samples(
    request: Request,
    q: Optional[str] = None,
    db: Session = Depends(get_db_dep),
):
    admin = current_admin(request)
    if admin is None:
        return _redirect_login()
    tenant_id = admin.tenant_id
    query = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.tenant_id == tenant_id, QCSkuItem.status == "active")
    )
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(
            QCSkuItem.item_number.ilike(pattern) | QCSkuItem.name.ilike(pattern)
        )
    skus = query.order_by(QCSkuItem.created_at.desc()).all()
    return templates.TemplateResponse(
        request,
        "sample_list.html",
        context={"skus": skus, "tenant_id": tenant_id, "admin": admin, "q": q or ""},
    )


# GET /admin/samples/new
@router.get("/samples/new", response_class=HTMLResponse)
def new_sample_form(request: Request):
    admin = current_admin(request)
    if admin is None:
        return _redirect_login()
    return templates.TemplateResponse(
        request,
        "sample_new.html",
        context={"tenant_id": admin.tenant_id, "admin": admin, "error": None},
    )


# POST /admin/samples
@router.post("/samples", response_class=HTMLResponse)
def create_sample(
    request: Request,
    item_number: str = Form(...),
    name: str = Form(...),
    category: Optional[str] = Form(default=None),
    description: Optional[str] = Form(default=None),
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    tenant_id = admin.tenant_id
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
                "admin": admin,
                "error": f"Item number '{item_number}' already exists.",
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
                "admin": admin,
                "error": f"Item number '{item_number}' already exists.",
                "item_number": item_number,
                "name": name,
                "category": category,
                "description": description,
            },
            status_code=409,
        )
    return RedirectResponse(url=f"/admin/samples/{sku.id}", status_code=303)


def _load_sku_or_404(db: Session, sku_id: str, tenant_id: str) -> QCSkuItem:
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    return sku


# GET /admin/samples/{sku_id}
@router.get("/samples/{sku_id}", response_class=HTMLResponse)
def sample_detail(
    sku_id: str,
    request: Request,
    db: Session = Depends(get_db_dep),
):
    admin = current_admin(request)
    if admin is None:
        return _redirect_login()
    sku = _load_sku_or_404(db, sku_id, admin.tenant_id)
    return templates.TemplateResponse(
        request,
        "sample_detail.html",
        context={
            "sku": sku,
            "primary_photo": _primary_photo(sku),
            "tenant_id": admin.tenant_id,
            "admin": admin,
        },
    )


# POST /admin/samples/{sku_id}/photos
@router.post("/samples/{sku_id}/photos", response_class=HTMLResponse)
async def add_photo(
    sku_id: str,
    request: Request,
    is_primary: bool = Form(default=False),
    angle: Optional[str] = Form(default=None),
    view_type: Optional[str] = Form(default=None),
    image_url: Optional[str] = Form(default=None),
    local_path_input: Optional[str] = Form(default=None),
    photo_file: Optional[UploadFile] = File(default=None),
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    tenant_id = admin.tenant_id
    # Reject any sku_id that is unsafe as a filesystem path component before use.
    validate_safe_id(sku_id, "sku_id")
    _load_sku_or_404(db, sku_id, tenant_id)

    now = _utcnow()
    sha256_hash: Optional[str] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    mime_type: Optional[str] = None
    saved_local_path: Optional[str] = None

    if photo_file and photo_file.filename:
        # Mode A: upload file to data/qc_samples/{tenant_id}/{sku_id}/photos/
        content = await photo_file.read()
        # Hardened upload (A3): size + MIME whitelist. Returns canonical MIME.
        mime_type = validate_image_upload(content, photo_file.content_type)
        sha256_hash = hashlib.sha256(content).hexdigest()

        try:
            import cv2
            import numpy as np
            np_arr = np.frombuffer(content, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img is not None:
                height_px, width_px = img.shape[:2]
        except Exception:
            pass

        # Canonical extension from validated MIME (never from user filename).
        ext = extension_for_mime(mime_type)
        filename = f"{_new_id()}{ext}"
        safe_tenant = validate_safe_id(tenant_id, "tenant_id")
        dest_dir = _DATA_DIR / safe_tenant / sku_id / "photos"
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
    return RedirectResponse(url=f"/admin/samples/{sku_id}", status_code=303)


# POST /admin/samples/{sku_id}/photos/{photo_id}/set-primary
@router.post("/samples/{sku_id}/photos/{photo_id}/set-primary", response_class=HTMLResponse)
def set_primary_photo(
    sku_id: str,
    photo_id: str,
    request: Request,
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    tenant_id = admin.tenant_id
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
    return RedirectResponse(url=f"/admin/samples/{sku_id}", status_code=303)


# POST /admin/samples/{sku_id}/requirements
@router.post("/samples/{sku_id}/requirements", response_class=HTMLResponse)
def add_requirement(
    sku_id: str,
    request: Request,
    code: str = Form(...),
    title: str = Form(...),
    requirement_text: str = Form(...),
    severity: str = Form(default="major"),
    pass_criteria: Optional[str] = Form(default=None),
    sort_order: int = Form(default=0),
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    tenant_id = admin.tenant_id
    _load_sku_or_404(db, sku_id, tenant_id)

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
    return RedirectResponse(url=f"/admin/samples/{sku_id}", status_code=303)


# POST /admin/samples/{sku_id}/detection-points
@router.post("/samples/{sku_id}/detection-points", response_class=HTMLResponse)
def add_detection_point(
    sku_id: str,
    request: Request,
    point_code: str = Form(...),
    label: str = Form(...),
    description: Optional[str] = Form(default=None),
    roi_json_text: Optional[str] = Form(default=None),
    severity: str = Form(default="major"),
    sort_order: int = Form(default=0),
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    tenant_id = admin.tenant_id
    _load_sku_or_404(db, sku_id, tenant_id)

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
    return RedirectResponse(url=f"/admin/samples/{sku_id}", status_code=303)


# POST /admin/samples/{sku_id}/archive
@router.post("/samples/{sku_id}/archive", response_class=HTMLResponse)
def archive_sample(
    sku_id: str,
    request: Request,
    admin: AdminSession = Depends(require_admin_session),
    db: Session = Depends(get_db_dep),
):
    tenant_id = admin.tenant_id
    sku = _load_sku_or_404(db, sku_id, tenant_id)
    sku.status = "archived"
    db.commit()
    return RedirectResponse(url="/admin/samples", status_code=303)
