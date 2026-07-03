"""FastAPI QC API router — all endpoints from §4.6.1–4.6.7."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from src.api.auth import Principal, require_principal
from src.api.deps import get_db_dep
from src.db.qc_models import (
    CapturePhoto,
    InspectionItemResult as DBInspectionItemResult,
    InspectionResult as DBInspectionResult,
    InspectionRun,
    ProductStandard,
    QCAsset,
    QCPoint,
    StandardPhoto,
    SyncJob,
    SyncTarget,
)
from src.events.qc_events import (
    build_asset_registered_event,
    build_inspection_completed_event,
    build_inspection_started_event,
    build_standard_created_event,
)
from src.qwen.schema import (
    CapturePhotoInput,
    FallbackInfo,
    InspectionContext,
    InspectionItemResult,
    QcPointInput,
    QwenInspectionOutput,
    StandardPhotoInput,
)
from src.qwen.service import QwenQCService

router = APIRouter(
    prefix="/api/v1/qc",
    tags=["qc"],
    dependencies=[Depends(require_principal)],
)


# ─── Request/Response Models ───────────────────────────────────────────────────


class CreateStandardRequest(BaseModel):
    tenant_id: str
    sku_id: str
    name: str
    version: str = "1.0"
    description: Optional[str] = None
    status: str = "draft"


class StandardResponse(BaseModel):
    id: str
    tenant_id: str
    sku_id: str
    name: str
    version: str
    status: str
    description: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreatePhotoRequest(BaseModel):
    tenant_id: str
    sku_id: str
    local_path: str
    angle: Optional[str] = None
    sha256: Optional[str] = None
    version: str = "1.0"


class PhotoResponse(BaseModel):
    id: str
    standard_id: str
    tenant_id: str
    sku_id: str
    angle: Optional[str]
    local_path: str
    sha256: Optional[str]
    version: str
    uploaded_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreateQCPointRequest(BaseModel):
    tenant_id: str
    qc_point_code: str
    name: str
    description: Optional[str] = None
    rule_type: Optional[str] = None
    roi_json: Optional[Dict[str, Any]] = None
    severity: str = "major"


class QCPointResponse(BaseModel):
    id: str
    standard_id: str
    tenant_id: str
    qc_point_code: str
    name: str
    description: Optional[str]
    rule_type: Optional[str]
    roi_json: Optional[Dict[str, Any]]
    severity: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UpdateQCPointRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    rule_type: Optional[str] = None
    roi_json: Optional[Dict[str, Any]] = None
    severity: Optional[str] = None
    is_active: Optional[bool] = None


class CreateCaptureRequest(BaseModel):
    tenant_id: str
    sku_id: str
    local_path: str
    sha256: Optional[str] = None
    capture_source: str = "manual"


class CaptureResponse(BaseModel):
    id: str
    tenant_id: str
    sku_id: str
    local_path: str
    sha256: Optional[str]
    captured_at: datetime
    capture_source: str

    model_config = ConfigDict(from_attributes=True)


class RunInspectionRequest(BaseModel):
    tenant_id: str
    sku_id: str
    standard_id: str
    capture_photo_id: str


class InspectionItemResultResponse(BaseModel):
    id: str
    qc_point_id: str
    qc_point_code: str
    name: str
    result: str
    confidence: float
    reason: Optional[str]
    evidence: Optional[Dict[str, Any]]

    model_config = ConfigDict(from_attributes=True)


class InspectionResultResponse(BaseModel):
    id: str
    inspection_run_id: str
    tenant_id: str
    overall_result: str
    confidence: float
    engine: str
    model_name: str
    summary: Optional[str]
    fallback_used: bool
    fallback_reason: Optional[str]
    created_at: datetime
    items: List[InspectionItemResultResponse] = []

    model_config = ConfigDict(from_attributes=True)


class InspectionRunResponse(BaseModel):
    id: str
    tenant_id: str
    sku_id: str
    standard_id: str
    capture_photo_id: str
    status: str
    overall_result: Optional[str]
    engine: Optional[str]
    model_name: Optional[str]
    confidence: Optional[float]
    summary: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class InspectionRunWithResultResponse(InspectionRunResponse):
    result: Optional[InspectionResultResponse] = None


class InspectionCompletedEvent(BaseModel):
    event: Dict[str, Any]
    inspection_run: InspectionRunResponse
    result: InspectionResultResponse


class AssetResponse(BaseModel):
    id: str
    tenant_id: str
    sku_id: str
    inspection_run_id: Optional[str]
    asset_type: str
    local_path: str
    sha256: Optional[str]
    file_size_bytes: Optional[int]
    mime_type: Optional[str]
    contains_pii: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CreateSyncTargetRequest(BaseModel):
    tenant_id: str
    name: str
    target_type: str
    config_json: Optional[Dict[str, Any]] = None
    is_active: bool = True


class SyncTargetResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    target_type: str
    config_json: Optional[Dict[str, Any]]
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SyncJobResponse(BaseModel):
    id: str
    tenant_id: str
    asset_id: str
    target_id: str
    status: str
    remote_path: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LatestResultResponse(BaseModel):
    sku_id: str
    tenant_id: str
    inspection_id: Optional[str]
    overall_result: Optional[str]
    confidence: Optional[float]
    engine: Optional[str]
    completed_at: Optional[datetime]


# ─── Helper ───────────────────────────────────────────────────────────────────


def _new_id() -> str:
    return uuid.uuid4().hex


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _forced_review_required(
    qc_point_inputs: List[QcPointInput],
    reason: str,
) -> QwenInspectionOutput:
    """Build a review_required output without consulting any provider.

    Used by the legacy /inspect route to fail closed when required inputs are
    missing — a provider must never get the chance to return a pass with no
    standard photos or no detection points.
    """
    items = [
        InspectionItemResult(
            qc_point_id=p.qc_point_id,
            qc_point_code=p.qc_point_code,
            name=p.name,
            result="review_required",
            confidence=0.0,
            reason=reason,
            evidence={},
        )
        for p in qc_point_inputs
    ]
    return QwenInspectionOutput(
        overall_result="review_required",
        engine="router",
        model_name="none",
        confidence=0.0,
        items=items,
        fallback=FallbackInfo(used=True, reason=reason),
        summary=f"Inspection deferred: {reason}",
    )


# ─── Standards ────────────────────────────────────────────────────────────────


@router.post("/standards", response_model=StandardResponse, status_code=status.HTTP_201_CREATED)
def create_standard(
    body: CreateStandardRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> StandardResponse:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    now = _utcnow()
    std = ProductStandard(
        id=_new_id(),
        tenant_id=body.tenant_id,
        sku_id=body.sku_id,
        name=body.name,
        version=body.version,
        description=body.description,
        status=body.status,
        created_at=now,
        updated_at=now,
    )
    db.add(std)
    db.commit()
    db.refresh(std)
    return std


@router.get("/standards/{standard_id}", response_model=StandardResponse)
def get_standard(
    standard_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> StandardResponse:
    tenant_id = principal.tenant_id
    std = (
        db.query(ProductStandard)
        .filter(ProductStandard.id == standard_id, ProductStandard.tenant_id == tenant_id)
        .first()
    )
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")
    return std


@router.get("/standards/by-sku/{sku_id}", response_model=List[StandardResponse])
def get_standards_by_sku(
    sku_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> List[StandardResponse]:
    tenant_id = principal.tenant_id
    return (
        db.query(ProductStandard)
        .filter(ProductStandard.sku_id == sku_id, ProductStandard.tenant_id == tenant_id)
        .all()
    )


# ─── Standard Photos ──────────────────────────────────────────────────────────


@router.post(
    "/standards/{standard_id}/photos",
    response_model=PhotoResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_standard_photo(
    standard_id: str,
    body: CreatePhotoRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> PhotoResponse:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    std = (
        db.query(ProductStandard)
        .filter(ProductStandard.id == standard_id, ProductStandard.tenant_id == body.tenant_id)
        .first()
    )
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")

    photo = StandardPhoto(
        id=_new_id(),
        standard_id=standard_id,
        tenant_id=body.tenant_id,
        sku_id=body.sku_id,
        angle=body.angle,
        local_path=body.local_path,
        sha256=body.sha256,
        version=body.version,
        uploaded_at=_utcnow(),
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


@router.get("/standards/{standard_id}/photos", response_model=List[PhotoResponse])
def list_standard_photos(
    standard_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> List[PhotoResponse]:
    tenant_id = principal.tenant_id
    std = (
        db.query(ProductStandard)
        .filter(ProductStandard.id == standard_id, ProductStandard.tenant_id == tenant_id)
        .first()
    )
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")
    return db.query(StandardPhoto).filter(StandardPhoto.standard_id == standard_id).all()


# ─── QC Points ────────────────────────────────────────────────────────────────


@router.post(
    "/standards/{standard_id}/qc-points",
    response_model=QCPointResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_qc_point(
    standard_id: str,
    body: CreateQCPointRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> QCPointResponse:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    std = (
        db.query(ProductStandard)
        .filter(ProductStandard.id == standard_id, ProductStandard.tenant_id == body.tenant_id)
        .first()
    )
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")

    point = QCPoint(
        id=_new_id(),
        standard_id=standard_id,
        tenant_id=body.tenant_id,
        qc_point_code=body.qc_point_code,
        name=body.name,
        description=body.description,
        rule_type=body.rule_type,
        roi_json=body.roi_json,
        severity=body.severity,
        is_active=True,
        created_at=_utcnow(),
    )
    db.add(point)
    db.commit()
    db.refresh(point)
    return point


@router.get("/standards/{standard_id}/qc-points", response_model=List[QCPointResponse])
def list_qc_points(
    standard_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> List[QCPointResponse]:
    tenant_id = principal.tenant_id
    std = (
        db.query(ProductStandard)
        .filter(ProductStandard.id == standard_id, ProductStandard.tenant_id == tenant_id)
        .first()
    )
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")
    return (
        db.query(QCPoint)
        .filter(QCPoint.standard_id == standard_id, QCPoint.is_active == True)
        .all()
    )


@router.put("/qc-points/{qc_point_id}", response_model=QCPointResponse)
def update_qc_point(
    qc_point_id: str,
    body: UpdateQCPointRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> QCPointResponse:
    tenant_id = principal.tenant_id
    point = (
        db.query(QCPoint)
        .filter(QCPoint.id == qc_point_id, QCPoint.tenant_id == tenant_id)
        .first()
    )
    if not point:
        raise HTTPException(status_code=404, detail="QC point not found")

    if body.name is not None:
        point.name = body.name
    if body.description is not None:
        point.description = body.description
    if body.rule_type is not None:
        point.rule_type = body.rule_type
    if body.roi_json is not None:
        point.roi_json = body.roi_json
    if body.severity is not None:
        point.severity = body.severity
    if body.is_active is not None:
        point.is_active = body.is_active

    db.commit()
    db.refresh(point)
    return point


# ─── Captures ─────────────────────────────────────────────────────────────────


@router.post(
    "/captures",
    response_model=CaptureResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_capture(
    body: CreateCaptureRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> CaptureResponse:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    capture = CapturePhoto(
        id=_new_id(),
        tenant_id=body.tenant_id,
        sku_id=body.sku_id,
        local_path=body.local_path,
        sha256=body.sha256,
        capture_source=body.capture_source,
        captured_at=_utcnow(),
    )
    db.add(capture)
    db.commit()
    db.refresh(capture)
    return capture


@router.get("/captures/{capture_id}", response_model=CaptureResponse)
def get_capture(
    capture_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> CaptureResponse:
    tenant_id = principal.tenant_id
    capture = (
        db.query(CapturePhoto)
        .filter(CapturePhoto.id == capture_id, CapturePhoto.tenant_id == tenant_id)
        .first()
    )
    if not capture:
        raise HTTPException(status_code=404, detail="Capture not found")
    return capture


# ─── Inspection ───────────────────────────────────────────────────────────────


@router.post(
    "/inspect",
    response_model=InspectionCompletedEvent,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
def run_inspection(
    body: RunInspectionRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> InspectionCompletedEvent:
    """Run a QC inspection against a product standard.

    Steps:
    1. Load standard + photos + QC points
    2. Load capture photo
    3. Run QwenRouter (uses FakeCloudQwenProvider when cloud disabled)
    4. Save InspectionRun + InspectionResult + InspectionItemResults
    5. Register QCAsset
    6. Build and return the event
    """
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    # 1. Load standard
    std = (
        db.query(ProductStandard)
        .filter(
            ProductStandard.id == body.standard_id,
            ProductStandard.tenant_id == body.tenant_id,
        )
        .first()
    )
    if not std:
        raise HTTPException(status_code=404, detail="Standard not found")

    # 2. Load capture photo
    capture = (
        db.query(CapturePhoto)
        .filter(
            CapturePhoto.id == body.capture_photo_id,
            CapturePhoto.tenant_id == body.tenant_id,
        )
        .first()
    )
    if not capture:
        raise HTTPException(status_code=404, detail="Capture photo not found")

    # Legacy-route guards (Option B): the standard and capture must both belong to
    # the requested SKU, otherwise the inspection compares mismatched products.
    if std.sku_id != body.sku_id:
        raise HTTPException(
            status_code=400,
            detail=f"standard.sku_id {std.sku_id!r} does not match request.sku_id {body.sku_id!r}",
        )
    if capture.sku_id != body.sku_id:
        raise HTTPException(
            status_code=400,
            detail=f"capture.sku_id {capture.sku_id!r} does not match request.sku_id {body.sku_id!r}",
        )

    # Load standard photos
    std_photos = (
        db.query(StandardPhoto)
        .filter(StandardPhoto.standard_id == body.standard_id)
        .all()
    )

    # Load QC points
    qc_points_db = (
        db.query(QCPoint)
        .filter(QCPoint.standard_id == body.standard_id, QCPoint.is_active == True)
        .all()
    )

    # Build schema inputs
    standard_photo_inputs = [
        StandardPhotoInput(
            photo_id=p.id,
            local_path=p.local_path,
            angle=p.angle,
        )
        for p in std_photos
    ]
    capture_photo_input = CapturePhotoInput(
        photo_id=capture.id,
        local_path=capture.local_path,
    )
    qc_point_inputs = [
        QcPointInput(
            qc_point_id=p.id,
            qc_point_code=p.qc_point_code,
            name=p.name,
            description=p.description or "",
            roi_json=p.roi_json,
            rule_type=p.rule_type,
        )
        for p in qc_points_db
    ]
    context = InspectionContext(
        tenant_id=body.tenant_id,
        sku_id=body.sku_id,
        standard_id=body.standard_id,
        inspection_id="",  # will be set after creating InspectionRun
    )

    # 3. Create InspectionRun
    now = _utcnow()
    inspection_id = _new_id()
    context = InspectionContext(
        tenant_id=body.tenant_id,
        sku_id=body.sku_id,
        standard_id=body.standard_id,
        inspection_id=inspection_id,
    )
    run = InspectionRun(
        id=inspection_id,
        tenant_id=body.tenant_id,
        sku_id=body.sku_id,
        standard_id=body.standard_id,
        capture_photo_id=body.capture_photo_id,
        status="running",
        started_at=now,
    )
    db.add(run)
    db.flush()  # get id without committing

    # 4. Run inspection.
    # Fail closed: without standard photos or without detection points there is
    # nothing a provider could legitimately pass, so never invoke one — force
    # review_required regardless of QC_ENGINE_MODE / cloud configuration.
    if not standard_photo_inputs or not qc_point_inputs:
        reason = (
            "no_standard_photos" if not standard_photo_inputs else "no_detection_points_defined"
        )
        qwen_output = _forced_review_required(qc_point_inputs, reason=reason)
    else:
        service = QwenQCService()
        qwen_output = service.run_inspection(
            standard_photos=standard_photo_inputs,
            captured_photo=capture_photo_input,
            qc_points=qc_point_inputs,
            context=context,
        )

    # Update run with results
    completed_at = _utcnow()
    run.status = "done"
    run.overall_result = qwen_output.overall_result
    run.engine = qwen_output.engine
    run.model_name = qwen_output.model_name
    run.confidence = qwen_output.confidence
    run.summary = qwen_output.summary
    run.completed_at = completed_at

    # 5. Save InspectionResult
    result_id = _new_id()
    db_result = DBInspectionResult(
        id=result_id,
        inspection_run_id=inspection_id,
        tenant_id=body.tenant_id,
        overall_result=qwen_output.overall_result,
        confidence=qwen_output.confidence,
        engine=qwen_output.engine,
        model_name=qwen_output.model_name,
        summary=qwen_output.summary,
        raw_output=qwen_output.model_dump(),
        fallback_used=qwen_output.fallback.used,
        fallback_reason=qwen_output.fallback.reason,
        created_at=completed_at,
    )
    db.add(db_result)
    db.flush()

    # Save InspectionItemResults
    for item in qwen_output.items:
        db_item = DBInspectionItemResult(
            id=_new_id(),
            inspection_result_id=result_id,
            tenant_id=body.tenant_id,
            qc_point_id=item.qc_point_id,
            qc_point_code=item.qc_point_code,
            name=item.name,
            result=item.result,
            confidence=item.confidence,
            reason=item.reason,
            evidence=item.evidence,
        )
        db.add(db_item)

    # 6. Register QCAsset for the capture photo
    asset_id = _new_id()
    asset = QCAsset(
        id=asset_id,
        tenant_id=body.tenant_id,
        sku_id=body.sku_id,
        inspection_run_id=inspection_id,
        asset_type="capture_photo",
        local_path=capture.local_path,
        sha256=capture.sha256,
        contains_pii=False,
        created_at=completed_at,
    )
    db.add(asset)
    db.commit()
    db.refresh(run)
    db.refresh(db_result)

    # Build item result responses
    item_responses = [
        InspectionItemResultResponse(
            id=item_row.id,
            qc_point_id=item_row.qc_point_id,
            qc_point_code=item_row.qc_point_code,
            name=item_row.name,
            result=item_row.result,
            confidence=item_row.confidence,
            reason=item_row.reason,
            evidence=item_row.evidence,
        )
        for item_row in db.query(DBInspectionItemResult)
        .filter(DBInspectionItemResult.inspection_result_id == result_id)
        .all()
    ]

    result_response = InspectionResultResponse(
        id=db_result.id,
        inspection_run_id=db_result.inspection_run_id,
        tenant_id=db_result.tenant_id,
        overall_result=db_result.overall_result,
        confidence=db_result.confidence,
        engine=db_result.engine,
        model_name=db_result.model_name,
        summary=db_result.summary,
        fallback_used=db_result.fallback_used,
        fallback_reason=db_result.fallback_reason,
        created_at=db_result.created_at,
        items=item_responses,
    )

    run_response = InspectionRunResponse(
        id=run.id,
        tenant_id=run.tenant_id,
        sku_id=run.sku_id,
        standard_id=run.standard_id,
        capture_photo_id=run.capture_photo_id,
        status=run.status,
        overall_result=run.overall_result,
        engine=run.engine,
        model_name=run.model_name,
        confidence=run.confidence,
        summary=run.summary,
        started_at=run.started_at,
        completed_at=run.completed_at,
    )

    event_payload = build_inspection_completed_event(
        tenant_id=body.tenant_id,
        inspection_id=inspection_id,
        sku_id=body.sku_id,
        standard_id=body.standard_id,
        overall_result=qwen_output.overall_result,
        confidence=qwen_output.confidence,
        engine=qwen_output.engine,
        model_name=qwen_output.model_name,
        item_count=len(qwen_output.items),
        fallback_used=qwen_output.fallback.used,
        summary=qwen_output.summary,
    )

    return InspectionCompletedEvent(
        event=event_payload,
        inspection_run=run_response,
        result=result_response,
    )


@router.get("/inspections/{inspection_id}", response_model=InspectionRunResponse)
def get_inspection(
    inspection_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> InspectionRunResponse:
    tenant_id = principal.tenant_id
    run = (
        db.query(InspectionRun)
        .filter(
            InspectionRun.id == inspection_id,
            InspectionRun.tenant_id == tenant_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return run


@router.get("/inspections/{inspection_id}/results", response_model=InspectionResultResponse)
def get_inspection_result(
    inspection_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> InspectionResultResponse:
    tenant_id = principal.tenant_id
    run = (
        db.query(InspectionRun)
        .filter(
            InspectionRun.id == inspection_id,
            InspectionRun.tenant_id == tenant_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Inspection not found")

    result = (
        db.query(DBInspectionResult)
        .filter(DBInspectionResult.inspection_run_id == inspection_id)
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Inspection result not found")

    items = (
        db.query(DBInspectionItemResult)
        .filter(DBInspectionItemResult.inspection_result_id == result.id)
        .all()
    )

    item_responses = [
        InspectionItemResultResponse(
            id=item.id,
            qc_point_id=item.qc_point_id,
            qc_point_code=item.qc_point_code,
            name=item.name,
            result=item.result,
            confidence=item.confidence,
            reason=item.reason,
            evidence=item.evidence,
        )
        for item in items
    ]

    return InspectionResultResponse(
        id=result.id,
        inspection_run_id=result.inspection_run_id,
        tenant_id=result.tenant_id,
        overall_result=result.overall_result,
        confidence=result.confidence,
        engine=result.engine,
        model_name=result.model_name,
        summary=result.summary,
        fallback_used=result.fallback_used,
        fallback_reason=result.fallback_reason,
        created_at=result.created_at,
        items=item_responses,
    )


# ─── Assets ───────────────────────────────────────────────────────────────────


@router.get("/assets/{asset_id}", response_model=AssetResponse)
def get_asset(
    asset_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> AssetResponse:
    tenant_id = principal.tenant_id
    asset = (
        db.query(QCAsset)
        .filter(QCAsset.id == asset_id, QCAsset.tenant_id == tenant_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset


@router.get("/assets/by-inspection/{inspection_id}", response_model=List[AssetResponse])
def get_assets_by_inspection(
    inspection_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> List[AssetResponse]:
    tenant_id = principal.tenant_id
    # Verify tenant owns inspection
    run = (
        db.query(InspectionRun)
        .filter(
            InspectionRun.id == inspection_id,
            InspectionRun.tenant_id == tenant_id,
        )
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Inspection not found")
    return (
        db.query(QCAsset)
        .filter(
            QCAsset.inspection_run_id == inspection_id,
            QCAsset.tenant_id == tenant_id,
        )
        .all()
    )


@router.get("/assets/by-sku/{sku_id}", response_model=List[AssetResponse])
def get_assets_by_sku(
    sku_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> List[AssetResponse]:
    tenant_id = principal.tenant_id
    return (
        db.query(QCAsset)
        .filter(QCAsset.sku_id == sku_id, QCAsset.tenant_id == tenant_id)
        .all()
    )


# ─── Latest Result ────────────────────────────────────────────────────────────


@router.get("/sku/{sku_id}/latest-result", response_model=LatestResultResponse)
def get_latest_sku_result(
    sku_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> LatestResultResponse:
    tenant_id = principal.tenant_id
    run = (
        db.query(InspectionRun)
        .filter(
            InspectionRun.sku_id == sku_id,
            InspectionRun.tenant_id == tenant_id,
            InspectionRun.status == "done",
        )
        .order_by(InspectionRun.completed_at.desc())
        .first()
    )
    if not run:
        return LatestResultResponse(
            sku_id=sku_id,
            tenant_id=tenant_id,
            inspection_id=None,
            overall_result=None,
            confidence=None,
            engine=None,
            completed_at=None,
        )
    return LatestResultResponse(
        sku_id=sku_id,
        tenant_id=tenant_id,
        inspection_id=run.id,
        overall_result=run.overall_result,
        confidence=run.confidence,
        engine=run.engine,
        completed_at=run.completed_at,
    )


# ─── Sync Targets ─────────────────────────────────────────────────────────────


@router.post(
    "/sync-targets",
    response_model=SyncTargetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_sync_target(
    body: CreateSyncTargetRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> SyncTargetResponse:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    target = SyncTarget(
        id=_new_id(),
        tenant_id=body.tenant_id,
        name=body.name,
        target_type=body.target_type,
        config_json=body.config_json,
        is_active=body.is_active,
        created_at=_utcnow(),
    )
    db.add(target)
    db.commit()
    db.refresh(target)
    return target


@router.get("/sync-targets", response_model=List[SyncTargetResponse])
def list_sync_targets(
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> List[SyncTargetResponse]:
    tenant_id = principal.tenant_id
    return (
        db.query(SyncTarget)
        .filter(SyncTarget.tenant_id == tenant_id, SyncTarget.is_active == True)
        .all()
    )


# ─── Sync Jobs ────────────────────────────────────────────────────────────────


@router.post(
    "/assets/{asset_id}/sync",
    response_model=SyncJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def trigger_asset_sync(
    asset_id: str,
    target_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> SyncJobResponse:
    tenant_id = principal.tenant_id
    asset = (
        db.query(QCAsset)
        .filter(QCAsset.id == asset_id, QCAsset.tenant_id == tenant_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    target = (
        db.query(SyncTarget)
        .filter(SyncTarget.id == target_id, SyncTarget.tenant_id == tenant_id)
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Sync target not found")

    job = SyncJob(
        id=_new_id(),
        tenant_id=tenant_id,
        asset_id=asset_id,
        target_id=target_id,
        status="pending",
        created_at=_utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("/sync-jobs/{job_id}", response_model=SyncJobResponse)
def get_sync_job(
    job_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> SyncJobResponse:
    tenant_id = principal.tenant_id
    job = (
        db.query(SyncJob)
        .filter(SyncJob.id == job_id, SyncJob.tenant_id == tenant_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Sync job not found")
    return job
