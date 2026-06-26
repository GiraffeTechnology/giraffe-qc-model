"""FastAPI router for QC Pad conversational UI."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.openclaw.qc_agent_bridge import QCAgentBridge, get_bridge
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


def _require_operator(request: Request) -> Optional[int]:
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
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return RedirectResponse(url="/pad/login", status_code=302)
    return templates.TemplateResponse(request, "pad_inspection.html", {"job_id": job_id})


@router.get("/pad/inspections/{job_id}/report", response_class=HTMLResponse)
async def pad_report(
    request: Request,
    job_id: str,
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
    if result.action_card:
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
    content = await image.read()
    return JSONResponse({
        "status": "received",
        "filename": image.filename,
        "size_bytes": len(content),
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


@router.get("/api/v1/pad/skus")
async def pad_search_skus(
    request: Request,
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db_dep),
):
    """Search active SKU catalog entries for the Pad selector."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")

    from src.db.sku_models import QCSkuItem

    query = db.query(QCSkuItem).filter_by(tenant_id=tenant_id, status="active")
    if q.strip():
        pattern = f"%{q.strip()}%"
        query = query.filter(or_(
            QCSkuItem.item_number.ilike(pattern),
            QCSkuItem.name.ilike(pattern),
            QCSkuItem.category.ilike(pattern),
        ))
    skus = query.order_by(QCSkuItem.item_number.asc()).limit(limit).all()
    return JSONResponse({
        "skus": [
            {
                "id": sku.id,
                "item_number": sku.item_number,
                "name": sku.name,
                "category": sku.category,
                "status": sku.status,
            }
            for sku in skus
        ]
    })


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
        "sku_id": revision.sku_id,
        "revision_id": revision.id,
        "confirmed_by": operator_id,
        "next_action": {
            "type": "start_inspection",
            "sku_id": revision.sku_id,
            "revision_id": revision.id,
        },
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
        "active_standard_revision_id": job.active_standard_revision_id,
        "operator_id": operator_id,
        "inspection_url": f"/pad/inspections/{job.id}",
    })


@router.post("/api/v1/pad/inspections/{job_id}/media")
async def pad_attach_inspection_media(
    request: Request,
    job_id: str,
    image: UploadFile = File(...),
    angle: Optional[str] = Form(default=None),
    view_type: Optional[str] = Form(default="inspection"),
    db: Session = Depends(get_db_dep),
):
    """Attach an uploaded Pad image to a concrete inspection job."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")

    from src.db.execution_models import QCInspectionJob
    from src.inspection.api_service import attach_inspection_media

    job = db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)

    content = await image.read()
    if not content:
        return JSONResponse({"error": "empty image upload"}, status_code=400)

    digest = hashlib.sha256(content).hexdigest()
    safe_name = os.path.basename(image.filename or "inspection-image.bin").replace("/", "_")
    media_dir = os.path.join(tempfile.gettempdir(), "giraffe_qc_pad_media", job_id)
    os.makedirs(media_dir, exist_ok=True)
    local_path = os.path.join(media_dir, f"{digest[:12]}_{safe_name}")
    with open(local_path, "wb") as fh:
        fh.write(content)

    media = attach_inspection_media(
        db,
        job_id=job_id,
        local_path=local_path,
        angle=angle,
        view_type=view_type,
        sha256=digest,
        mime_type=image.content_type,
        tenant_id=tenant_id,
    )
    return JSONResponse({
        "status": "media_attached",
        "media_id": media.id,
        "job_id": job_id,
        "filename": image.filename,
        "size_bytes": len(content),
        "sha256": digest,
        "local_path": local_path,
    }, status_code=201)


@router.post("/api/v1/pad/inspections/{job_id}/run_model")
async def pad_run_model(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    """Run the Pad model adapter and ingest output through the existing QC service."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")

    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        body = {}

    from src.db.execution_models import QCCheckpointResult, QCInspectionJob, QCInspectionMedia
    from src.inspection.api_service import ingest_model_output
    from src.pad.model_adapter import DeterministicPadQCAdapter

    job = db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)

    media_id = body.get("media_id")
    media = None
    if media_id:
        media = db.query(QCInspectionMedia).filter_by(id=media_id, job_id=job_id, tenant_id=tenant_id).first()
        if media is None:
            return JSONResponse({"error": "media not found for this job"}, status_code=404)
    else:
        media = (
            db.query(QCInspectionMedia)
            .filter_by(job_id=job_id, tenant_id=tenant_id)
            .order_by(QCInspectionMedia.created_at.desc())
            .first()
        )

    adapter = DeterministicPadQCAdapter()
    adapter_result = adapter.run(db, job_id=job_id, media=media, options=body)
    try:
        model_result = ingest_model_output(
            db,
            job_id=job_id,
            provider=adapter_result.provider,
            model_name=adapter_result.model_name,
            raw_output=adapter_result.raw_output,
            media_id=media.id if media else None,
            http_status=200,
            elapsed_ms=adapter_result.elapsed_ms,
            tenant_id=tenant_id,
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    checkpoint_rows = db.query(QCCheckpointResult).filter_by(job_id=job_id).all()
    return JSONResponse({
        "status": "model_output_ingested",
        "job_id": job_id,
        "media_id": media.id if media else None,
        "model_result_id": model_result.id,
        "checkpoint_results": [
            {
                "point_code": row.detection_point.point_code,
                "label": row.detection_point.label,
                "result": row.result,
                "observed_value": row.observed_value,
                "confidence": row.confidence,
                "notes": row.notes,
            }
            for row in checkpoint_rows
        ],
    }, status_code=201)


@router.post("/api/v1/pad/inspections/{job_id}/finalize")
async def pad_finalize_inspection(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    """Finalize a Pad inspection job using the authoritative QC verdict service."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")

    from src.db.execution_models import QCInspectionJob
    from src.inspection.api_service import finalize_inspection_job

    job = db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)
    try:
        report = finalize_inspection_job(db, job_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({
        "status": "finalized",
        "job_id": job_id,
        "overall_result": report.overall_result,
        "report_id": report.id,
        "checkpoint_results_count": report.checkpoint_results_count,
        "findings_count": report.findings_count,
        "report_url": f"/pad/inspections/{job_id}/report",
    })


@router.get("/api/v1/pad/inspections/{job_id}/report")
async def pad_inspection_report_json(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    """Return a detailed Pad report card JSON for rendering on the tablet."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")

    from src.db.execution_models import QCCheckpointResult, QCIncidentalFinding, QCInspectionJob
    from src.inspection.api_service import get_inspection_report

    job = db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)
    try:
        report = get_inspection_report(db, job_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=404)

    checkpoint_rows = db.query(QCCheckpointResult).filter_by(job_id=job_id).all()
    finding_rows = db.query(QCIncidentalFinding).filter_by(job_id=job_id).all()
    return JSONResponse({
        "job": {
            "id": job.id,
            "sku_id": job.sku_id,
            "tenant_id": job.tenant_id,
            "active_standard_revision_id": job.active_standard_revision_id,
            "status": job.status,
        },
        "report": {
            "id": report.id,
            "overall_result": report.overall_result,
            "summary_text": report.summary_text,
            "checkpoint_results_count": report.checkpoint_results_count,
            "findings_count": report.findings_count,
        },
        "checkpoint_results": [
            {
                "point_code": row.detection_point.point_code,
                "label": row.detection_point.label,
                "expected_value": row.detection_point.expected_value,
                "result": row.result,
                "observed_value": row.observed_value,
                "confidence": row.confidence,
                "notes": row.notes,
            }
            for row in checkpoint_rows
        ],
        "incidental_findings": [
            {
                "severity": row.severity,
                "description": row.description,
                "location_hint": row.location_hint,
                "evidence_json": row.evidence_json,
            }
            for row in finding_rows
        ],
        "audit": {
            "operator_id": operator_id,
            "tenant_id": tenant_id,
            "job_id": job_id,
        },
    })
