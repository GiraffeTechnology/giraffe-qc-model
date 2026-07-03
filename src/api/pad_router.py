"""FastAPI router for QC Pad conversational UI."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.api.uploads import read_upload_limited, validate_image_upload
from src.openclaw.qc_agent_bridge import QCAgentBridge, get_bridge
from src.pad.agent_service import process_pad_message
from src.pad.session_service import (
    authenticate_operator,
    get_operator_by_id,
    get_or_create_conversation_session,
    seed_demo_operators,
    update_preferred_language,
)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

router = APIRouter()


def _get_bridge() -> QCAgentBridge:
    return get_bridge()


def _require_operator(request: Request) -> int:
    operator_id = request.session.get("operator_id")
    if not operator_id:
        return None
    return int(operator_id)


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------

@router.get("/pad/login", response_class=HTMLResponse)
async def pad_login_page(request: Request):
    return templates.TemplateResponse(request, "pad_login.html", {"error": None})


@router.post("/pad/login")
async def pad_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    tenant_id: str = Form(default="demo"),
    db: Session = Depends(get_db_dep),
):
    seed_demo_operators(db, tenant_id)
    operator = authenticate_operator(db, username, password, tenant_id)
    if operator is None:
        return templates.TemplateResponse(
            request, "pad_login.html", {"error": "Invalid credentials"}, status_code=401
        )
    request.session["operator_id"] = str(operator.id)
    request.session["tenant_id"] = tenant_id
    return RedirectResponse(url="/pad", status_code=302)


@router.post("/pad/logout")
async def pad_logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/pad/login", status_code=302)


@router.get("/pad", response_class=HTMLResponse)
async def pad_workspace(
    request: Request,
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return RedirectResponse(url="/pad/login", status_code=302)
    operator = get_operator_by_id(db, operator_id)
    if operator is None:
        request.session.clear()
        return RedirectResponse(url="/pad/login", status_code=302)
    return templates.TemplateResponse(
        request,
        "pad_workspace.html",
        {"operator": operator, "preferred_language": operator.preferred_language},
    )


@router.get("/pad/inspections/{job_id}", response_class=HTMLResponse)
async def pad_inspection(
    request: Request,
    job_id: int,
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return RedirectResponse(url="/pad/login", status_code=302)
    return templates.TemplateResponse(request, "pad_inspection.html", {"job_id": job_id})


@router.get("/pad/inspections/{job_id}/report", response_class=HTMLResponse)
async def pad_report(
    request: Request,
    job_id: int,
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return RedirectResponse(url="/pad/login", status_code=302)
    return templates.TemplateResponse(request, "pad_report.html", {"job_id": job_id})


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@router.post("/api/v1/pad/chat")
async def pad_chat(
    request: Request,
    db: Session = Depends(get_db_dep),
    bridge: QCAgentBridge = Depends(_get_bridge),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")

    body: Dict[str, Any] = await request.json()
    raw_text: str = body.get("message", "")
    context: Dict[str, Any] = body.get("context", {})

    operator = get_operator_by_id(db, operator_id)
    preferred_language = operator.preferred_language if operator else "en"

    result = process_pad_message(
        db=db,
        operator_id=operator_id,
        tenant_id=tenant_id,
        preferred_language=preferred_language,
        raw_text=raw_text,
        context=context,
        bridge=bridge,
    )
    # standard_confirmation cards are already fully structured in payload;
    # other cards expose payload nested under "type".
    if result.action_card:
        if result.action_card.action_type == "standard_confirmation":
            action_card_data = result.action_card.payload
        else:
            action_card_data = result.action_card.payload
    else:
        action_card_data = None

    return JSONResponse({
        "reply": result.reply_text,
        "detected_language": result.detected_language,
        "intent": result.intent,
        "confidence": result.confidence,
        "requires_confirmation": result.requires_confirmation,
        "action_card": action_card_data,
    })


@router.post("/api/v1/pad/voice")
async def pad_voice(
    request: Request,
    audio: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return JSONResponse({
        "status": "transcript_required",
        "message": "Voice input received. Please confirm the transcript before submitting.",
    })


@router.post("/api/v1/pad/upload")
async def pad_upload(
    request: Request,
    image: UploadFile = File(...),
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    # Bounded streaming read (A3): reject oversize input before it is fully
    # accumulated in memory, then enforce the MIME whitelist by content sniff.
    content = await read_upload_limited(image)
    mime = validate_image_upload(content, image.content_type)
    return JSONResponse({
        "status": "received",
        "filename": image.filename,
        "size_bytes": len(content),
        "mime_type": mime,
        "message": "Image uploaded successfully",
    })


@router.get("/api/v1/pad/session")
async def pad_session_info(
    request: Request,
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")
    operator = get_operator_by_id(db, operator_id)
    if operator is None:
        return JSONResponse({"error": "operator not found"}, status_code=404)
    conv_session = get_or_create_conversation_session(
        db, operator_id, tenant_id, operator.preferred_language
    )
    return JSONResponse({
        "operator_id": operator_id,
        "tenant_id": tenant_id,
        "preferred_language": operator.preferred_language,
        "session_id": conv_session.id,
        "session_status": conv_session.status,
    })


@router.post("/api/v1/pad/language")
async def pad_set_language(
    request: Request,
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    body: Dict[str, Any] = await request.json()
    language: str = body.get("language", "en")
    operator = update_preferred_language(db, operator_id, language)
    if operator is None:
        return JSONResponse({"error": "operator not found"}, status_code=404)
    return JSONResponse({"preferred_language": operator.preferred_language})


@router.post("/api/v1/pad/confirm_standard")
async def pad_confirm_standard(
    request: Request,
    db: Session = Depends(get_db_dep),
):
    """Explicit operator confirmation before any standard DB write."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")
    body: Dict[str, Any] = await request.json()
    intake_id: Optional[str] = body.get("intake_id")
    if intake_id is None:
        return JSONResponse({"error": "intake_id required"}, status_code=400)

    from src.db.intake_models import QCStandardIntake
    intake = db.query(QCStandardIntake).filter_by(id=intake_id).first()
    if intake is None:
        return JSONResponse({"error": "intake not found"}, status_code=404)

    confirmed_checkpoints: list = body.get("confirmed_checkpoints") or []
    if not confirmed_checkpoints and intake.extracted_json:
        confirmed_checkpoints = intake.extracted_json.get("checkpoints", [])

    try:
        from src.intake.service import confirm_standard_intake
        revision, _conf = confirm_standard_intake(
            db,
            intake_id=intake_id,
            confirmed_by=str(operator_id),
            confirmed_checkpoints=confirmed_checkpoints,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "status": "confirmed",
        "intake_id": intake_id,
        "revision_id": revision.id,
        "confirmed_by": operator_id,
    })


@router.post("/api/v1/pad/create_inspection_job")
async def pad_create_inspection_job(
    request: Request,
    db: Session = Depends(get_db_dep),
):
    """Create an inspection job from the pad UI."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")
    body: Dict[str, Any] = await request.json()
    sku_id: Optional[str] = body.get("sku_id")
    if not sku_id:
        return JSONResponse({"error": "sku_id required"}, status_code=400)
    try:
        from src.inspection.api_service import create_inspection_job_from_api
        job = create_inspection_job_from_api(
            db,
            sku_id=str(sku_id),
            tenant_id=tenant_id,
            created_by=str(operator_id),
            job_ref=body.get("job_ref"),
            notes=body.get("notes"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "status": "job_created",
        "job_id": job.id,
        "sku_id": job.sku_id,
        "operator_id": operator_id,
    })
