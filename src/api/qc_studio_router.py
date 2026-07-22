"""Admin Studio router — chat-first SKU + standard training (S2, PRD §5.1–§5.6).

Mounts the three-panel ``/admin/studio`` page and its backend routes:

* ``GET  /admin/studio``                     — three-panel Studio page
* ``GET  /admin/studio/skus``                — SKU list / search / status filter
* ``GET  /admin/studio/skus/{sku_id}``       — SKU card (right panel)
* ``POST /admin/studio/chat``                — conversational SKU create + extract
* ``POST /admin/samples/upload``             — hardened standard-photo upload
* ``GET  /admin/studio/photos/{photo_id}``   — serve a stored standard photo
* ``POST /admin/studio/confirm``             — confirm / reject detection points
* ``POST /admin/studio/detection-points/{detection_point_id}/regions`` — set region annotations (§2)
* ``POST /admin/studio/publish``             — publish signed L2 bundle
* ``GET  /admin/studio/bundles/{bundle_id}/download`` — download signed .tar.gz (re-verified)
* ``GET  /admin/studio/skus/{sku_id}/bundles`` — bundle history (S3 owns the UI)

Extraction, confirmation and upload validation are reused from existing
hardened modules — this router only wires them to the chat surface.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.db.sku_models import QCDetectionPoint, QCSkuItem, QCStandardPhoto, SKU_LIFECYCLE_STATES
from src.db.pad_models import QCConversationMessage
from src.db.studio_models import QCPublishBundle
from src.intake.service import confirm_standard_intake, reject_standard_intake
from src.qc_model.studio import service as studio
from src.qc_model.studio import ai_gateway
from src.qc_model.studio.regions import InvalidRegion, set_detection_point_regions
from src.qc_model.studio.analysis_config import (
    InvalidAnalysisConfig,
    set_detection_point_analysis_config,
)
from src.storage.upload_validation import (
    UploadValidationError,
    read_and_validate_document_upload,
    read_and_validate_upload,
    validate_image_content,
)
from src.qc_model.ingestion.process_card import (
    REAL_TEXT_EXTRACTION_EXTENSIONS,
    extract_process_card_text,
)
from src.api.authz import effective_actor, effective_tenant
from src.api.admin_auth import current_admin
from src.api.sample_security import (
    require_sample_surface_mutation,
    verify_sample_mutation_credential,
)
from src.api.uploads import validate_safe_id
from src.api.sample_admin_router import resolve_sample_photo_path
from src.db.sku_models import QCSkuStandardRevision
from src.pad.session_service import get_or_create_conversation_session
from src.qc_model.qualification import training as training_service
from src.qc_model.qualification.training_gate import evaluate_training_gate
from src.web.i18n import install_i18n, resolve_language

router = APIRouter(tags=["admin-studio"])

_LEGACY_STUDIO_DATA_DIR = Path("data/qc_studio")
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
# Carry the shared web-shell language switch on the Studio page (S1 seam).
install_i18n(templates)

_STUDIO_DATA_DIR = Path(os.getenv("QC_STUDIO_DATA_DIR", "data/qc_studio"))
_SAMPLE_DATA_DIR = Path(os.getenv("QC_SAMPLE_DATA_DIR", "data/qc_samples"))


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conversation_session(request: Request, db: Session):
    admin = current_admin(request)
    if admin is None:
        return None
    return get_or_create_conversation_session(
        db, admin.operator_id, admin.tenant_id, resolve_language(request)
    )


def _record_message(
    request: Request,
    db: Session,
    *,
    role: str,
    text: str,
    intent: Optional[str] = None,
    action: Optional[Dict[str, Any]] = None,
) -> None:
    conversation = _conversation_session(request, db)
    if conversation is None:
        return
    db.add(QCConversationMessage(
        tenant_id=conversation.tenant_id,
        session_id=conversation.id,
        operator_id=conversation.operator_id,
        role=role,
        source_language=resolve_language(request),
        preferred_language=resolve_language(request),
        raw_text_original=text,
        translated_output_text=text if role == "assistant" else None,
        intent=intent,
        action_json=json.dumps(action or {}, ensure_ascii=False, separators=(",", ":")),
    ))
    db.commit()


# ── Page ──────────────────────────────────────────────────────────────────────


@router.get("/admin/studio", response_class=HTMLResponse)
def studio_page(request: Request, tenant_id: str = "default", sku_id: str = ""):
    from src.db.sku_models import SKU_LIFECYCLE_STATES
    tenant_id = effective_tenant(request, tenant_id)

    return templates.TemplateResponse(
        request,
        "admin_studio.html",
        {
            "tenant_id": tenant_id,
            "initial_sku_id": sku_id,
            "sku_lifecycle_states": list(SKU_LIFECYCLE_STATES),
        },
    )


# ── SKU list / search / status filter (left panel) ────────────────────────────


@router.get("/admin/studio/config")
def studio_config():
    """Shared Studio configuration consumed by web and Pad administrators."""
    return {
        "sku_lifecycle_states": list(SKU_LIFECYCLE_STATES),
        "assistants": ai_gateway.assistant_status(),
    }


@router.get("/admin/studio/assistants")
def studio_assistants():
    """Configured live assistants; endpoint addresses are intentionally hidden."""
    return ai_gateway.assistant_status()


@router.get("/admin/studio/conversation")
def studio_conversation(request: Request, db: Session = Depends(get_db_dep)):
    conversation = _conversation_session(request, db)
    if conversation is None:
        return {"messages": []}
    messages = (
        db.query(QCConversationMessage)
        .filter_by(session_id=conversation.id, tenant_id=conversation.tenant_id)
        .order_by(QCConversationMessage.created_at.desc())
        .limit(80)
        .all()
    )
    return {"messages": [
        {"role": item.role, "text": item.translated_output_text or item.raw_text_original or ""}
        for item in reversed(messages)
    ]}


class CreateStudioSkuRequest(BaseModel):
    tenant_id: str = "default"
    item_number: str
    name: str
    category: Optional[str] = None
    description: Optional[str] = None


@router.post(
    "/admin/studio/skus",
    status_code=201,
    dependencies=[Depends(require_sample_surface_mutation)],
)
def create_studio_sku(body: CreateStudioSkuRequest, db: Session = Depends(get_db_dep)):
    """Create an Administrator-authored SKU at the first shared lifecycle state."""
    item_number = body.item_number.strip()
    name = body.name.strip()
    if not item_number or not name:
        raise HTTPException(status_code=400, detail="item number and name are required")
    now = _now()
    sku = QCSkuItem(
        id=_uid(),
        tenant_id=body.tenant_id,
        item_number=item_number,
        name=name,
        category=body.category,
        description=body.description,
        status=SKU_LIFECYCLE_STATES[0],
        created_at=now,
        updated_at=now,
    )
    db.add(sku)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="item number already exists") from exc
    db.refresh(sku)
    return studio.sku_summary(db, sku)


@router.get("/admin/studio/skus")
def list_skus(
    request: Request,
    q: str = "",
    status: str = "",
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    tenant_id = effective_tenant(request, tenant_id)
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
    request: Request,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    tenant_id = effective_tenant(request, tenant_id)
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


@router.post(
    "/admin/studio/chat",
    dependencies=[Depends(require_sample_surface_mutation)],
)
async def studio_chat(request: Request, body: ChatRequest, db: Session = Depends(get_db_dep)):
    tenant_id = effective_tenant(request, body.tenant_id)
    actor = effective_actor(request, body.operator_id)
    _record_message(request, db, role="user", text=body.message)
    config = ai_gateway.text_config()
    if not config.configured:
        # The deterministic parser is only a CI/test adapter. A deployed Studio
        # must fail closed instead of pretending a model call occurred.
        if os.getenv("APP_ENV", "production").lower() != "test":
            raise HTTPException(status_code=503, detail="text assistant is not configured")
        result = studio.process_studio_chat(
            db,
            tenant_id=tenant_id,
            message=body.message,
            current_sku_id=body.sku_id,
            operator_id=actor,
        )
    else:
        current = None
        if body.sku_id:
            sku = db.query(QCSkuItem).filter_by(id=body.sku_id, tenant_id=tenant_id).first()
            current = studio.sku_summary(db, sku) if sku else None
        try:
            ai_result = await asyncio.to_thread(
                ai_gateway.author_text,
                message=body.message,
                language=resolve_language(request),
                current_sku=current,
            )
        except ai_gateway.StudioAIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        result = studio.process_structured_ai_turn(
            db,
            tenant_id=tenant_id,
            message=body.message,
            ai_result=ai_result,
            current_sku_id=body.sku_id,
            operator_id=actor,
        )
    payload = result.to_dict()
    _record_message(
        request,
        db,
        role="assistant",
        text=result.reply,
        intent=result.action,
        action={"sku_id": result.sku.get("id") if result.sku else None},
    )
    return payload

@router.post(
    "/admin/studio/import-standard",
    dependencies=[Depends(require_sample_surface_mutation)],
)
async def studio_import_standard(
    request: Request,
    sku_id: str = Form(...),
    tenant_id: str = Form("default"),
    source_kind: str = Form("file"),
    document: UploadFile = File(...),
    db: Session = Depends(get_db_dep),
):
    """Turn a process card or standard file into a 9B-authored draft.

    Images are OCR'd first. All recovered text then follows the same text-
    assistant and administrator confirmation path as natural-language input.
    """
    tenant_id = effective_tenant(request, tenant_id)
    validate_safe_id(sku_id, "sku_id")
    sku = db.query(QCSkuItem).filter_by(id=sku_id, tenant_id=tenant_id).first()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    if source_kind not in {"process_card", "file"}:
        raise HTTPException(status_code=400, detail="invalid import source")

    filename = document.filename or ""
    try:
        validated = await read_and_validate_document_upload(document, filename=filename)
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    supported = {".jpg", ".jpeg", ".png", ".pdf"} | set(REAL_TEXT_EXTRACTION_EXTENSIONS)
    if validated.extension not in supported:
        raise HTTPException(
            status_code=415,
            detail="This file type cannot yet be converted to text for standard authoring.",
        )

    dest_dir = _STUDIO_DATA_DIR / tenant_id / sku_id / "standard_imports"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{_uid()}{validated.extension}"
    dest_path.write_bytes(validated.content)

    extracted_text: str | None = None
    ocr_used = False
    extraction_assistant = None
    if validated.extension in {".jpg", ".jpeg", ".png"}:
        try:
            image = validate_image_content(validated.content)
        except UploadValidationError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
        if not ai_gateway.vision_config().configured:
            raise HTTPException(status_code=503, detail="OCR assistant is not configured")
        try:
            ocr = await asyncio.to_thread(
                ai_gateway.extract_image_text,
                image_path=dest_path,
                mime_type=image.mime_type,
                language=resolve_language(request),
            )
        except ai_gateway.StudioAIError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        extracted_text = ocr["text"]
        ocr_used = True
        extraction_assistant = ocr.get("assistant")
    elif validated.extension == ".pdf":
        extracted_text = await asyncio.to_thread(extract_process_card_text, dest_path)
        if not extracted_text:
            if not ai_gateway.vision_config().configured:
                raise HTTPException(status_code=503, detail="OCR assistant is not configured")
            page_prefix = dest_dir / f"{dest_path.stem}-page"
            try:
                rendered = await asyncio.to_thread(
                    subprocess.run,
                    ["pdftoppm", "-png", "-r", "150", "-f", "1", "-l", "10",
                     str(dest_path), str(page_prefix)],
                    capture_output=True, check=False, timeout=60,
                )
            except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
                raise HTTPException(status_code=503, detail="PDF OCR renderer is unavailable") from exc
            pages = sorted(dest_dir.glob(f"{page_prefix.name}-*.png"))
            if rendered.returncode != 0 or not pages:
                raise HTTPException(status_code=422, detail="PDF pages could not be prepared for OCR")
            page_texts = []
            assistants = []
            for page in pages:
                try:
                    ocr = await asyncio.to_thread(
                        ai_gateway.extract_image_text,
                        image_path=page,
                        mime_type="image/png",
                        language=resolve_language(request),
                    )
                except ai_gateway.StudioAIError as exc:
                    raise HTTPException(status_code=502, detail=str(exc)) from exc
                page_texts.append(ocr["text"])
                assistants.append(ocr.get("assistant"))
            extracted_text = "\n\n".join(page_texts)
            ocr_used = True
            extraction_assistant = assistants
    elif validated.extension in REAL_TEXT_EXTRACTION_EXTENSIONS:
        extracted_text = await asyncio.to_thread(extract_process_card_text, dest_path)
    if not extracted_text:
        raise HTTPException(status_code=422, detail="No readable standard text was found.")

    if not ai_gateway.text_config().configured:
        raise HTTPException(status_code=503, detail="text assistant is not configured")
    import_message = (
        f"Imported {source_kind} '{filename}'. Convert the following source text "
        "into a complete QC standard draft without inventing missing values:\n"
        f"{extracted_text}"
    )
    try:
        ai_result = await asyncio.to_thread(
            ai_gateway.author_text,
            message=import_message,
            language=resolve_language(request),
            current_sku=studio.sku_summary(db, sku),
        )
    except ai_gateway.StudioAIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    result = studio.process_structured_ai_turn(
        db,
        tenant_id=tenant_id,
        message=import_message,
        ai_result=ai_result,
        current_sku_id=sku.id,
        operator_id=effective_actor(request),
        source_channel="studio_import_live_ai",
    )
    _record_message(
        request, db, role="user", text=f"Imported {source_kind}: {filename}",
    )
    _record_message(
        request, db, role="assistant", text=result.reply, intent=result.action,
        action={"sku_id": sku.id, "source_kind": source_kind},
    )
    payload = result.to_dict()
    payload["import"] = {
        "source_kind": source_kind,
        "filename": filename,
        "ocr_used": ocr_used,
        "extraction_assistant": extraction_assistant,
    }
    return payload


# ── Voice toggle (§5.3) — controlled not-enabled response, never crashes ──────


@router.post("/admin/studio/voice")
def studio_voice():
    return JSONResponse(
        {"status": "not_enabled", "message": "Voice input is not enabled yet."}
    )


# ── Standard photo upload (§5.3) ──────────────────────────────────────────────


@router.post(
    "/admin/samples/upload",
    dependencies=[Depends(require_sample_surface_mutation)],
)
async def sample_workbench_upload(
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

    dest_dir = _SAMPLE_DATA_DIR / tenant_id / sku_id / "photos"
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

    analysis = None
    analysis_error = None
    config = ai_gateway.vision_config()
    if config.configured:
        try:
            ai_result = await asyncio.to_thread(
                ai_gateway.author_image,
                image_path=dest_path,
                mime_type=validated.mime_type,
                language=resolve_language(request),
                current_sku=studio.sku_summary(db, sku),
            )
            analysis = studio.process_structured_ai_turn(
                db,
                tenant_id=tenant_id,
                message=f"Reference photo {photo.id} visual analysis",
                ai_result=ai_result,
                current_sku_id=sku.id,
                operator_id=effective_actor(request),
                source_channel="studio_image_live_ai",
            ).to_dict()
            _record_message(
                request,
                db,
                role="assistant",
                text=analysis["reply"],
                intent=analysis["action"],
                action={"sku_id": sku.id, "photo_id": photo.id},
            )
        except ai_gateway.StudioAIError as exc:
            analysis_error = str(exc)
    elif os.getenv("APP_ENV", "production").lower() != "test":
        analysis_error = "vision assistant is not configured"

    return {
        "status": "uploaded",
        "photo_id": photo.id,
        "url": studio.photo_url(photo),
        "mime_type": validated.mime_type,
        "size_bytes": validated.size_bytes,
        "sha256": validated.sha256,
        "sku": studio.sku_summary(db, sku),
        "analysis": analysis,
        "analysis_error": analysis_error,
    }


def _resolve_studio_photo_path(local_path: str) -> Path | None:
    sample_path = resolve_sample_photo_path(local_path)
    if sample_path is not None:
        return sample_path
    path = Path(local_path)
    if not path.is_absolute():
        try:
            suffix = path.relative_to(_LEGACY_STUDIO_DATA_DIR)
        except ValueError:
            return None
        path = _STUDIO_DATA_DIR / suffix
    resolved = path.resolve()
    root = _STUDIO_DATA_DIR.resolve()
    if resolved != root and root not in resolved.parents:
        return None
    return resolved


@router.get("/admin/studio/photos/{photo_id}")
def serve_photo(
    photo_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    photo = db.query(QCStandardPhoto).filter_by(id=photo_id, tenant_id=tenant_id).first()
    if photo is None or not photo.local_path:
        raise HTTPException(status_code=404, detail="Photo not found")
    path = _resolve_studio_photo_path(photo.local_path)
    if path is None or not path.is_file():
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
    expected_features: Dict[str, Any] = {}
    cv_config: Dict[str, Any] = {}


class ConfirmRequest(BaseModel):
    tenant_id: str = "default"
    intake_id: str
    confirmed_by: Optional[str] = None
    checkpoints: List[ConfirmCheckpoint]
    question_answers: Dict[str, str] = {}
    operator_comment: Optional[str] = None


@router.post(
    "/admin/studio/confirm",
    dependencies=[Depends(require_sample_surface_mutation)],
)
def studio_confirm(request: Request, body: ConfirmRequest, db: Session = Depends(get_db_dep)):
    tenant_id = effective_tenant(request, body.tenant_id)
    actor = effective_actor(request, body.confirmed_by)
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
            confirmed_by=actor,
            confirmed_checkpoints=checkpoints,
            question_answers=body.question_answers,
            operator_comment=body.operator_comment,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    sku = db.query(QCSkuItem).filter_by(id=revision.sku_id, tenant_id=tenant_id).first()
    if sku is not None:
        sku.status = "confirmed"
        sku.updated_at = _now()
        db.commit()
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
    rejected_by: Optional[str] = None
    reason: Optional[str] = None


@router.post(
    "/admin/studio/reject",
    dependencies=[Depends(require_sample_surface_mutation)],
)
def studio_reject(request: Request, body: RejectRequest, db: Session = Depends(get_db_dep)):
    tenant_id = effective_tenant(request, body.tenant_id)
    actor = effective_actor(request, body.rejected_by)
    try:
        intake = reject_standard_intake(
            db,
            intake_id=body.intake_id,
            rejected_by=actor,
            reason=body.reason,
            tenant_id=tenant_id,
        )
    except Exception as exc:  # noqa: BLE001 - surface as 400
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"status": intake.status, "intake_id": intake.id}


# ── Region annotation (§2) ────────────────────────────────────────────────────


class SetRegionsRequest(BaseModel):
    tenant_id: str = "default"
    regions: List[Dict[str, Any]] = []


class UpdateStudioDetectionPointRequest(BaseModel):
    tenant_id: str = "default"
    point_code: str
    label: str
    description: Optional[str] = None
    expected_value: Optional[str] = None
    method_hint: Optional[str] = None
    severity: str = "major"
    pass_criteria: Optional[str] = None


@router.patch(
    "/admin/studio/detection-points/{detection_point_id}",
    dependencies=[Depends(require_sample_surface_mutation)],
)
def studio_update_detection_point(
    detection_point_id: str,
    body: UpdateStudioDetectionPointRequest,
    db: Session = Depends(get_db_dep),
):
    """Edit checkpoint judgment fields behind the Administrator auth gate."""
    point = (
        db.query(QCDetectionPoint)
        .filter_by(id=detection_point_id, tenant_id=body.tenant_id, is_active=True)
        .first()
    )
    if point is None:
        raise HTTPException(status_code=404, detail="Detection point not found")
    expected_value = (
        body.expected_value if "expected_value" in body.model_fields_set else point.expected_value
    )
    pass_criteria = (
        body.pass_criteria if "pass_criteria" in body.model_fields_set else point.pass_criteria
    )
    if not body.point_code.strip() or not body.label.strip():
        raise HTTPException(status_code=400, detail="point code and label are required")
    if body.method_hint == "counting" and not (expected_value or "").strip():
        raise HTTPException(status_code=400, detail="counting checkpoint needs an expected count")
    if body.severity not in {"minor", "major", "critical"}:
        raise HTTPException(status_code=400, detail="unsupported severity")

    already_published = db.query(QCPublishBundle.id).filter_by(
        tenant_id=body.tenant_id,
        standard_revision_id=point.standard_revision_id,
    ).first()
    judgment_changed = any((
        point.point_code != body.point_code.strip(),
        point.label != body.label.strip(),
        point.method_hint != body.method_hint,
        point.expected_value != expected_value,
        point.pass_criteria != pass_criteria,
        point.severity != body.severity,
    ))
    if already_published and judgment_changed:
        raise HTTPException(
            status_code=409,
            detail="judgment-field edits after publish require a new qualified revision",
        )

    point.point_code = body.point_code.strip()
    point.label = body.label.strip()
    point.description = body.description
    point.method_hint = body.method_hint
    point.expected_value = expected_value
    point.pass_criteria = pass_criteria
    point.severity = body.severity
    point.updated_at = _now()
    db.commit()
    db.refresh(point)
    return {
        "id": point.id,
        "point_code": point.point_code,
        "label": point.label,
        "description": point.description,
        "method_hint": point.method_hint,
        "expected_value": point.expected_value,
        "pass_criteria": point.pass_criteria,
        "severity": point.severity,
        "regions": point.regions_json or [],
    }


@router.post(
    "/admin/studio/detection-points/{detection_point_id}/regions",
    dependencies=[Depends(require_sample_surface_mutation)],
)
def studio_set_regions(
    detection_point_id: str,
    body: SetRegionsRequest,
    db: Session = Depends(get_db_dep),
):
    """Spatially ground a detection point on one or more standard photos.

    Real caller for :func:`~src.qc_model.studio.regions.set_detection_point_regions`
    -- previously only exercised by tests. Fail-closed: an out-of-bounds box, an
    unknown ``image_id``, or an extra key rejects the whole request (§2), and
    the detection point's regions are left untouched.
    """
    try:
        dp = set_detection_point_regions(
            db,
            detection_point_id=detection_point_id,
            regions=body.regions,
            tenant_id=body.tenant_id,
        )
    except InvalidRegion as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    sku = db.query(QCSkuItem).filter_by(id=dp.sku_id, tenant_id=body.tenant_id).first()
    return {
        "status": "regions_saved",
        "detection_point_id": dp.id,
        "regions": dp.regions_json or [],
        "sku": studio.sku_summary(db, sku) if sku else None,
    }


class SetAnalysisConfigRequest(BaseModel):
    tenant_id: str = "default"
    expected_features: Dict[str, Any] = {}
    cv_config: Dict[str, Any] = {}


@router.post(
    "/admin/studio/detection-points/{detection_point_id}/analysis-config",
    dependencies=[Depends(require_sample_surface_mutation)],
)
def studio_set_analysis_config(
    detection_point_id: str,
    body: SetAnalysisConfigRequest,
    db: Session = Depends(get_db_dep),
):
    """Persist WS8 analyzer hooks before publish; no provider/model coupling."""
    try:
        point = set_detection_point_analysis_config(
            db, detection_point_id, body.expected_features, body.cv_config, body.tenant_id,
        )
    except InvalidAnalysisConfig as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    sku = db.query(QCSkuItem).filter_by(id=point.sku_id, tenant_id=body.tenant_id).first()
    return {
        "status": "analysis_config_saved",
        "detection_point_id": point.id,
        "expected_features": point.expected_features_json or {},
        "cv_config": point.cv_config_json or {},
        "sku": studio.sku_summary(db, sku) if sku else None,
    }


# ── Training step (§9.5-9.8): CV+VLM judgment + per-decision admin review ────


def _active_revision(db: Session, sku_id: str, tenant_id: str) -> Optional[QCSkuStandardRevision]:
    return (
        db.query(QCSkuStandardRevision)
        .filter_by(sku_id=sku_id, tenant_id=tenant_id, status="active")
        .order_by(QCSkuStandardRevision.revision_no.desc())
        .first()
    )


@router.post("/admin/studio/skus/{sku_id}/training/judgments")
async def studio_record_training_judgment(
    sku_id: str,
    request: Request,
    tenant_id: str = Form("default"),
    ground_truth_label: str = Form(...),
    ground_truth_notes: Optional[str] = Form(None),
    sample_photo_id: str = Form(...),
    db: Session = Depends(get_db_dep),
):
    """Run a CV+VLM judgment using a confirmed photo from Sample & Standard.

    Digital QC Studio never captures or uploads training photos. It may only
    call a tenant-owned sample photo already collected in Sample & Standard.
    """
    tenant_id = effective_tenant(request, tenant_id)
    sku = db.query(QCSkuItem).filter_by(id=sku_id, tenant_id=tenant_id).first()
    if sku is None:
        raise HTTPException(status_code=404, detail="SKU not found")
    revision = _active_revision(db, sku_id, tenant_id)
    if revision is None:
        return JSONResponse(
            {"error": "SKU has no active confirmed standard revision to train against"},
            status_code=400,
        )
    sample_photo = db.query(QCStandardPhoto).filter_by(
        id=sample_photo_id, sku_id=sku_id, tenant_id=tenant_id,
    ).first()
    if sample_photo is None:
        return JSONResponse({"error": "labeled sample photo not found"}, status_code=404)
    if sample_photo.is_primary:
        return JSONResponse({"error": "primary standard photo cannot be used as a training instance"}, status_code=400)
    if not sample_photo.local_path:
        return JSONResponse({"error": "labeled sample photo is not stored locally"}, status_code=400)
    dest_path = resolve_sample_photo_path(sample_photo.local_path)
    if dest_path is None or not dest_path.is_file():
        return JSONResponse({"error": "labeled sample photo file is unavailable"}, status_code=400)
    mime_type = sample_photo.mime_type or "image/jpeg"
    if not mime_type.startswith("image/"):
        return JSONResponse({"error": "labeled sample photo is not an image"}, status_code=400)

    dest_dir = _STUDIO_DATA_DIR / tenant_id / sku_id / "training"
    dest_dir.mkdir(parents=True, exist_ok=True)
    evidence_root = dest_dir / "cv-evidence"

    try:
        judgment = training_service.record_training_judgment(
            db,
            tenant_id=tenant_id, sku_id=sku_id, standard_revision_id=revision.id,
            image_path=dest_path, mime_type=mime_type,
            language=resolve_language(request),
            ground_truth_label=ground_truth_label,
            ground_truth_notes=ground_truth_notes,
            evidence_root=evidence_root,
        )
    except training_service.TrainingError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except ai_gateway.StudioAIError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)
    return {"status": "awaiting_admin_review", "judgment": training_service.judgment_view(judgment)}


@router.get("/admin/studio/skus/{sku_id}/training/judgments")
def studio_list_training_judgments(
    sku_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    """The pending review queue -- unreviewed judgments only (PRD §9.7 item 7)."""
    pending = training_service.list_pending_judgments(db, tenant_id=tenant_id, sku_id=sku_id)
    return {"judgments": [training_service.judgment_view(j) for j in pending]}


class TrainingDecisionRequest(BaseModel):
    tenant_id: str = "default"
    admin_id: Optional[str] = None
    decision: str
    correction: Optional[Dict[str, Any]] = None


@router.post("/admin/studio/training/judgments/{judgment_id}/decision")
def studio_submit_training_decision(
    judgment_id: str,
    request: Request,
    body: TrainingDecisionRequest,
    db: Session = Depends(get_db_dep),
):
    tenant_id = effective_tenant(request, body.tenant_id)
    admin_id = effective_actor(request, body.admin_id)
    try:
        judgment = training_service.submit_training_decision(
            db,
            judgment_id=judgment_id, tenant_id=tenant_id, admin_id=admin_id,
            decision=body.decision, correction=body.correction,
        )
    except training_service.TrainingError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"status": "reviewed", "judgment": training_service.judgment_view(judgment)}


@router.get("/admin/studio/skus/{sku_id}/training/status")
def studio_training_status(
    sku_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    revision = _active_revision(db, sku_id, tenant_id)
    if revision is None:
        return {"status": None, "message": "no active confirmed standard revision"}
    status = evaluate_training_gate(
        db, tenant_id=tenant_id, sku_id=sku_id, standard_revision_id=revision.id,
    )
    return {"standard_revision_id": revision.id, "status": status.to_dict()}


# ── Publish signed L2 bundle (§5.6) ───────────────────────────────────────────


class PublishRequest(BaseModel):
    tenant_id: str = "default"
    sku_id: str
    published_by: Optional[str] = None
    mutation_credential: Optional[str] = None


@router.post("/admin/studio/publish")
def studio_publish(request: Request, body: PublishRequest, db: Session = Depends(get_db_dep)):
    verify_sample_mutation_credential(request, db, body.mutation_credential)
    tenant_id = effective_tenant(request, body.tenant_id)
    actor = effective_actor(request, body.published_by)
    try:
        bundle = studio.publish_bundle(
            db,
            sku_id=body.sku_id,
            tenant_id=tenant_id,
            published_by=actor,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    sku = db.query(QCSkuItem).filter_by(id=body.sku_id, tenant_id=tenant_id).first()
    if sku is not None:
        sku.status = "published"
        sku.updated_at = _now()
        db.commit()
    return {
        "status": "published",
        "bundle": studio.bundle_view(bundle),
        "sku": studio.sku_summary(db, sku) if sku else None,
    }


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
