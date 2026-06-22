"""FastAPI SKU catalog router — Android-compatible SKU search and detail API."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.db.sku_models import (
    QCDetectionPoint,
    QCInspectionRequirement,
    QCSkuItem,
    QCStandardPhoto,
)

router = APIRouter(prefix="/api/v1/sku", tags=["sku"])


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─── Request / Response schemas ────────────────────────────────────────────────


class CreateSkuRequest(BaseModel):
    tenant_id: str = "default"
    item_number: str
    name: str
    category: Optional[str] = None
    description: Optional[str] = None


class SkuSearchItem(BaseModel):
    id: str
    item_number: str
    name: str
    reference_image_url: Optional[str]
    standard_photo_path: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class SkuSearchResponse(BaseModel):
    items: List[SkuSearchItem]


class PhotoResponse(BaseModel):
    id: str
    image_url: Optional[str]
    local_path: Optional[str]
    angle: Optional[str]
    view_type: Optional[str]
    sha256: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class RequirementResponse(BaseModel):
    id: str
    code: str
    title: str
    requirement_text: str
    severity: str
    pass_criteria: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class DetectionPointResponse(BaseModel):
    id: str
    point_code: str
    label: str
    description: Optional[str]
    roi_json: Optional[Dict[str, Any]]
    severity: str

    model_config = ConfigDict(from_attributes=True)


class SkuDetailResponse(BaseModel):
    id: str
    item_number: str
    name: str
    category: Optional[str]
    description: Optional[str]
    reference_image_url: Optional[str]
    standard_photo_path: Optional[str]
    photos: List[PhotoResponse]
    inspection_requirements: List[RequirementResponse]
    detection_points: List[DetectionPointResponse]

    model_config = ConfigDict(from_attributes=True)


class CreateSkuResponse(BaseModel):
    id: str
    tenant_id: str
    item_number: str
    name: str
    category: Optional[str]
    description: Optional[str]
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AddPhotoRequest(BaseModel):
    tenant_id: str = "default"
    image_url: Optional[str] = None
    local_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    angle: Optional[str] = None
    view_type: Optional[str] = None
    sha256: Optional[str] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    mime_type: Optional[str] = None
    is_primary: bool = False


class AddRequirementRequest(BaseModel):
    tenant_id: str = "default"
    code: str
    title: str
    requirement_text: str
    severity: str = "major"
    pass_criteria: Optional[str] = None
    tolerance_json: Optional[Dict[str, Any]] = None
    sort_order: int = 0


class AddDetectionPointRequest(BaseModel):
    tenant_id: str = "default"
    requirement_id: Optional[str] = None
    point_code: str
    label: str
    description: Optional[str] = None
    roi_json: Optional[Dict[str, Any]] = None
    expected_value: Optional[str] = None
    method_hint: Optional[str] = None
    severity: str = "major"
    sort_order: int = 0


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _primary_photo(sku: QCSkuItem) -> Optional[QCStandardPhoto]:
    for p in sku.photos:
        if p.is_primary:
            return p
    return sku.photos[0] if sku.photos else None


def _sku_to_search_item(sku: QCSkuItem) -> SkuSearchItem:
    photo = _primary_photo(sku)
    return SkuSearchItem(
        id=sku.id,
        item_number=sku.item_number,
        name=sku.name,
        reference_image_url=photo.image_url if photo else None,
        standard_photo_path=photo.local_path if photo else None,
    )


def _sku_to_detail(sku: QCSkuItem) -> SkuDetailResponse:
    photo = _primary_photo(sku)
    return SkuDetailResponse(
        id=sku.id,
        item_number=sku.item_number,
        name=sku.name,
        category=sku.category,
        description=sku.description,
        reference_image_url=photo.image_url if photo else None,
        standard_photo_path=photo.local_path if photo else None,
        photos=[
            PhotoResponse(
                id=p.id,
                image_url=p.image_url,
                local_path=p.local_path,
                angle=p.angle,
                view_type=p.view_type,
                sha256=p.sha256,
            )
            for p in sku.photos
        ],
        inspection_requirements=[
            RequirementResponse(
                id=r.id,
                code=r.code,
                title=r.title,
                requirement_text=r.requirement_text,
                severity=r.severity,
                pass_criteria=r.pass_criteria,
            )
            for r in sku.inspection_requirements
            if r.is_active
        ],
        detection_points=[
            DetectionPointResponse(
                id=dp.id,
                point_code=dp.point_code,
                label=dp.label,
                description=dp.description,
                roi_json=dp.roi_json,
                severity=dp.severity,
            )
            for dp in sku.detection_points
            if dp.is_active
        ],
    )


# ─── Endpoints ────────────────────────────────────────────────────────────────

# POST /api/v1/sku — must be registered before /{sku_id} routes
@router.post("", response_model=CreateSkuResponse, status_code=status.HTTP_201_CREATED)
def create_sku(
    body: CreateSkuRequest,
    db: Session = Depends(get_db_dep),
) -> CreateSkuResponse:
    now = _utcnow()
    sku = QCSkuItem(
        id=_new_id(),
        tenant_id=body.tenant_id,
        item_number=body.item_number,
        name=body.name,
        category=body.category,
        description=body.description,
        status="active",
        created_at=now,
        updated_at=now,
    )
    db.add(sku)
    db.commit()
    db.refresh(sku)
    return sku


# GET /api/v1/sku/search — must be registered before /{sku_id} to avoid path collision
@router.get("/search", response_model=SkuSearchResponse)
def search_sku(
    q: str = Query(default=""),
    tenant_id: str = Query(default="default"),
    db: Session = Depends(get_db_dep),
) -> SkuSearchResponse:
    if not q.strip():
        return SkuSearchResponse(items=[])

    pattern = f"%{q}%"
    skus = (
        db.query(QCSkuItem)
        .filter(
            QCSkuItem.tenant_id == tenant_id,
            QCSkuItem.status == "active",
            (QCSkuItem.item_number.ilike(pattern) | QCSkuItem.name.ilike(pattern)),
        )
        .all()
    )
    return SkuSearchResponse(items=[_sku_to_search_item(s) for s in skus])


@router.get("/{sku_id}", response_model=SkuDetailResponse)
def get_sku(
    sku_id: str,
    tenant_id: str = Query(default="default"),
    db: Session = Depends(get_db_dep),
) -> SkuDetailResponse:
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    return _sku_to_detail(sku)


@router.post("/{sku_id}/photos", status_code=status.HTTP_201_CREATED)
def add_photo(
    sku_id: str,
    body: AddPhotoRequest,
    db: Session = Depends(get_db_dep),
) -> dict:
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == body.tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    now = _utcnow()
    if body.is_primary:
        db.query(QCStandardPhoto).filter(
            QCStandardPhoto.sku_id == sku_id
        ).update({"is_primary": False})

    photo = QCStandardPhoto(
        id=_new_id(),
        tenant_id=body.tenant_id,
        sku_id=sku_id,
        image_url=body.image_url,
        local_path=body.local_path,
        thumbnail_url=body.thumbnail_url,
        angle=body.angle,
        view_type=body.view_type,
        sha256=body.sha256,
        width_px=body.width_px,
        height_px=body.height_px,
        mime_type=body.mime_type,
        is_primary=body.is_primary,
        created_at=now,
        updated_at=now,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return {"id": photo.id, "sku_id": sku_id, "is_primary": photo.is_primary}


@router.post("/{sku_id}/requirements", status_code=status.HTTP_201_CREATED)
def add_requirement(
    sku_id: str,
    body: AddRequirementRequest,
    db: Session = Depends(get_db_dep),
) -> dict:
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == body.tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    now = _utcnow()
    req = QCInspectionRequirement(
        id=_new_id(),
        tenant_id=body.tenant_id,
        sku_id=sku_id,
        code=body.code,
        title=body.title,
        requirement_text=body.requirement_text,
        severity=body.severity,
        pass_criteria=body.pass_criteria,
        tolerance_json=body.tolerance_json,
        sort_order=body.sort_order,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return {"id": req.id, "sku_id": sku_id, "code": req.code}


@router.post("/{sku_id}/detection-points", status_code=status.HTTP_201_CREATED)
def add_detection_point(
    sku_id: str,
    body: AddDetectionPointRequest,
    db: Session = Depends(get_db_dep),
) -> dict:
    sku = (
        db.query(QCSkuItem)
        .filter(QCSkuItem.id == sku_id, QCSkuItem.tenant_id == body.tenant_id)
        .first()
    )
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")

    now = _utcnow()
    dp = QCDetectionPoint(
        id=_new_id(),
        tenant_id=body.tenant_id,
        sku_id=sku_id,
        requirement_id=body.requirement_id,
        point_code=body.point_code,
        label=body.label,
        description=body.description,
        roi_json=body.roi_json,
        expected_value=body.expected_value,
        method_hint=body.method_hint,
        severity=body.severity,
        sort_order=body.sort_order,
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(dp)
    db.commit()
    db.refresh(dp)
    return {"id": dp.id, "sku_id": sku_id, "point_code": dp.point_code}
