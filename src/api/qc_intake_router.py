"""FastAPI router for QC standard intake pipeline."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.auth import Principal, require_principal
from src.api.deps import get_db_dep
from src.intake.service import (
    attach_intake_media,
    confirm_standard_intake,
    create_standard_intake,
    extract_standard_draft,
    reject_standard_intake,
)

router = APIRouter(
    prefix="/api/v1/qc/intakes",
    tags=["qc-intake"],
    dependencies=[Depends(require_principal)],
)


def _get_intake_for_tenant(db: Session, intake_id: str, tenant_id: str):
    """Fetch an intake scoped to the caller's tenant, or raise 404.

    Tenant scoping is enforced here so a valid token for one tenant can never
    read or mutate another tenant's intake by guessing its id.
    """
    from src.db.intake_models import QCStandardIntake

    intake = (
        db.query(QCStandardIntake)
        .filter_by(id=intake_id, tenant_id=tenant_id)
        .first()
    )
    if intake is None:
        raise HTTPException(status_code=404, detail="Intake not found")
    return intake


# ── Request / Response schemas ────────────────────────────────────────────────


class CreateIntakeRequest(BaseModel):
    tenant_id: Optional[str] = None
    sku_id: str
    raw_text: str
    source_type: str = "api"
    source_channel: Optional[str] = None
    source_message_id: Optional[str] = None
    operator_id: Optional[str] = None


class AttachMediaRequest(BaseModel):
    tenant_id: Optional[str] = None
    media_type: str = "image"
    media_role: str = "standard_photo"
    image_url: Optional[str] = None
    local_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    sha256: Optional[str] = None
    mime_type: Optional[str] = None
    width_px: Optional[int] = None
    height_px: Optional[int] = None
    duration_ms: Optional[int] = None
    metadata_json: Optional[Dict[str, Any]] = None


class CheckpointDraft(BaseModel):
    point_code: str
    label: str
    description: Optional[str] = None
    method_hint: Optional[str] = None
    severity: str = "major"
    expected_value: Optional[str] = None
    pass_criteria: Optional[str] = None


class ConfirmIntakeRequest(BaseModel):
    tenant_id: Optional[str] = None
    confirmed_by: str
    checkpoints: List[CheckpointDraft]
    operator_comment: Optional[str] = None


class RejectIntakeRequest(BaseModel):
    tenant_id: Optional[str] = None
    rejected_by: str
    reason: Optional[str] = None


class IntakeResponse(BaseModel):
    id: str
    tenant_id: str
    sku_id: str
    source_type: str
    status: str
    raw_text: Optional[str]
    extracted_json: Optional[Dict[str, Any]]
    confirmation_payload_json: Optional[Dict[str, Any]]
    confidence_score: Optional[float]
    parser_version: Optional[str]


class ConfirmResponse(BaseModel):
    revision_id: str
    revision_no: int
    status: str
    sku_id: str
    confirmed_by: str
    confirmation_id: str
    checkpoint_count: int


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("", status_code=201)
def create_intake(
    body: CreateIntakeRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> IntakeResponse:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    try:
        intake = create_standard_intake(
            db,
            sku_id=body.sku_id,
            tenant_id=body.tenant_id,
            raw_text=body.raw_text,
            source_type=body.source_type,
            source_channel=body.source_channel,
            source_message_id=body.source_message_id,
            operator_id=body.operator_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return IntakeResponse(
        id=intake.id,
        tenant_id=intake.tenant_id,
        sku_id=intake.sku_id,
        source_type=intake.source_type,
        status=intake.status,
        raw_text=intake.raw_text,
        extracted_json=intake.extracted_json,
        confirmation_payload_json=intake.confirmation_payload_json,
        confidence_score=intake.confidence_score,
        parser_version=intake.parser_version,
    )


@router.get("/{intake_id}")
def get_intake(
    intake_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> IntakeResponse:
    intake = _get_intake_for_tenant(db, intake_id, principal.tenant_id)
    return IntakeResponse(
        id=intake.id,
        tenant_id=intake.tenant_id,
        sku_id=intake.sku_id,
        source_type=intake.source_type,
        status=intake.status,
        raw_text=intake.raw_text,
        extracted_json=intake.extracted_json,
        confirmation_payload_json=intake.confirmation_payload_json,
        confidence_score=intake.confidence_score,
        parser_version=intake.parser_version,
    )


@router.post("/{intake_id}/media", status_code=201)
def add_intake_media(
    intake_id: str,
    body: AttachMediaRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> dict:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    _get_intake_for_tenant(db, intake_id, principal.tenant_id)
    try:
        media = attach_intake_media(
            db,
            intake_id=intake_id,
            media_type=body.media_type,
            media_role=body.media_role,
            image_url=body.image_url,
            local_path=body.local_path,
            thumbnail_url=body.thumbnail_url,
            sha256=body.sha256,
            mime_type=body.mime_type,
            width_px=body.width_px,
            height_px=body.height_px,
            duration_ms=body.duration_ms,
            metadata_json=body.metadata_json,
            tenant_id=body.tenant_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"id": media.id, "intake_id": intake_id, "media_type": media.media_type}


@router.post("/{intake_id}/extract")
def extract_draft(
    intake_id: str,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> IntakeResponse:
    _get_intake_for_tenant(db, intake_id, principal.tenant_id)
    try:
        intake = extract_standard_draft(db, intake_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return IntakeResponse(
        id=intake.id,
        tenant_id=intake.tenant_id,
        sku_id=intake.sku_id,
        source_type=intake.source_type,
        status=intake.status,
        raw_text=intake.raw_text,
        extracted_json=intake.extracted_json,
        confirmation_payload_json=intake.confirmation_payload_json,
        confidence_score=intake.confidence_score,
        parser_version=intake.parser_version,
    )


@router.post("/{intake_id}/confirm")
def confirm_intake(
    intake_id: str,
    body: ConfirmIntakeRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> ConfirmResponse:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    _get_intake_for_tenant(db, intake_id, principal.tenant_id)
    checkpoints = [cp.model_dump() for cp in body.checkpoints]
    try:
        revision, conf = confirm_standard_intake(
            db,
            intake_id=intake_id,
            confirmed_by=body.confirmed_by,
            confirmed_checkpoints=checkpoints,
            operator_comment=body.operator_comment,
            tenant_id=body.tenant_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Count active detection points on the new revision
    from src.db.sku_models import QCDetectionPoint
    cp_count = (
        db.query(QCDetectionPoint)
        .filter_by(standard_revision_id=revision.id, is_active=True)
        .count()
    )
    return ConfirmResponse(
        revision_id=revision.id,
        revision_no=revision.revision_no,
        status=revision.status,
        sku_id=revision.sku_id,
        confirmed_by=conf.confirmed_by,
        confirmation_id=conf.id,
        checkpoint_count=cp_count,
    )


@router.post("/{intake_id}/reject")
def reject_intake(
    intake_id: str,
    body: RejectIntakeRequest,
    principal: Principal = Depends(require_principal),
    db: Session = Depends(get_db_dep),
) -> dict:
    body.tenant_id = principal.resolve_tenant(body.tenant_id)
    _get_intake_for_tenant(db, intake_id, principal.tenant_id)
    try:
        intake = reject_standard_intake(
            db,
            intake_id=intake_id,
            rejected_by=body.rejected_by,
            reason=body.reason,
            tenant_id=body.tenant_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"id": intake.id, "status": intake.status}
