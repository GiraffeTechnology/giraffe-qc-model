"""FastAPI router for QC Pad conversational UI."""
from __future__ import annotations

from pathlib import Path
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from src.api.deps import get_db_dep
from src.openclaw.qc_agent_bridge import QCAgentBridge, get_bridge
from src.pad.agent_service import process_pad_message
from src.pad.session_service import (
    authenticate_operator,
    get_operator_by_id,
    get_or_create_conversation_session,
    seed_demo_operators,
    update_preferred_language,
)
from src.web.i18n import install_i18n, persist_language, resolve_language, translate

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_i18n(templates)

router = APIRouter()


def _get_bridge() -> QCAgentBridge:
    return get_bridge()


def _require_operator(request: Request) -> int:
    operator_id = request.session.get("operator_id")
    if not operator_id:
        return None
    return int(operator_id)


def _fallback_crop_boxes(point, cv_record: dict[str, Any]) -> list[dict[str, float]]:
    """Use authored ROIs first, then deterministic CV geometry."""
    boxes: list[dict[str, float]] = []
    for region in point.regions_json or []:
        if all(key in region for key in ("x", "y", "w", "h")):
            boxes.append({key: float(region[key]) for key in ("x", "y", "w", "h")})
    if boxes:
        return boxes
    analysis = cv_record.get("analysis") or {}
    for result in analysis.get("analyzers") or []:
        candidates = list(result.get("boxes") or [])
        if result.get("box"):
            candidates.append(result["box"])
        for polygon in result.get("polygons") or []:
            if not polygon:
                continue
            xs = [float(p["x"]) for p in polygon]
            ys = [float(p["y"]) for p in polygon]
            candidates.append({
                "x": min(xs), "y": min(ys),
                "w": max(xs) - min(xs), "h": max(ys) - min(ys),
            })
        for box in candidates:
            if isinstance(box, dict) and all(key in box for key in ("x", "y", "w", "h")):
                boxes.append({key: float(box[key]) for key in ("x", "y", "w", "h")})
    return boxes


def _write_fallback_crops(
    image_path: Path,
    *,
    job_id: str,
    points: list,
    cv_records: list[dict[str, Any]],
) -> tuple[dict[str, list[Path]], list[dict[str, Any]]]:
    """Persist ≤200 KB per-point JPEG crops for any cloud escalation."""
    import cv2

    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        return {}, []
    height, width = image.shape[:2]
    records_by_code = {item["point_code"]: item for item in cv_records}
    crop_dir = image_path.parent / "fallback-crops" / job_id
    crop_dir.mkdir(parents=True, exist_ok=True)
    by_code: dict[str, list[Path]] = {}
    metadata: list[dict[str, Any]] = []
    for point in points:
        cv_record = records_by_code.get(point.point_code, {})
        for index, box in enumerate(_fallback_crop_boxes(point, cv_record), start=1):
            x1 = max(0, min(width - 1, int(round(box["x"] * width))))
            y1 = max(0, min(height - 1, int(round(box["y"] * height))))
            x2 = max(x1 + 1, min(width, int(round((box["x"] + box["w"]) * width))))
            y2 = max(y1 + 1, min(height, int(round((box["y"] + box["h"]) * height))))
            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            crop_height, crop_width = crop.shape[:2]
            longest = max(crop_height, crop_width)
            if longest > 768:
                scale = 768 / longest
                crop = cv2.resize(
                    crop,
                    (max(1, int(round(crop_width * scale))), max(1, int(round(crop_height * scale)))),
                    interpolation=cv2.INTER_AREA,
                )
            encoded = None
            quality_used = None
            for quality in (88, 76, 64, 52, 40):
                ok, candidate = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, quality])
                if ok and candidate.nbytes <= 200 * 1024:
                    encoded = candidate.tobytes()
                    quality_used = quality
                    break
            if encoded is None:
                continue
            target = crop_dir / f"{point.point_code}-{index}.jpg"
            target.write_bytes(encoded)
            by_code.setdefault(point.point_code, []).append(target)
            metadata.append({
                "point_code": point.point_code,
                "path": str(target),
                "size_bytes": len(encoded),
                "jpeg_quality": quality_used,
                "source_box": box,
            })
    return by_code, metadata


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
            request,
            "pad_login.html",
            {"error": translate("pad.login.invalid", resolve_language(request))},
            status_code=401,
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
    response = JSONResponse({"preferred_language": operator.preferred_language})
    # Keep the shell language cookie in sync so page chrome (templates) renders
    # in the operator's language after reload, not just agent replies.
    persist_language(response, operator.preferred_language)
    return response


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


@router.get("/api/v1/pad/skus")
async def pad_search_skus(
    request: Request,
    q: str = Query(default=""),
    db: Session = Depends(get_db_dep),
):
    """Tenant-scoped SKU search for the authenticated Operator Web simulator."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")
    from src.db.sku_models import QCSkuItem, QCSkuStandardRevision, QCStandardPhoto

    query = (
        db.query(QCSkuItem)
        .join(
            QCSkuStandardRevision,
            (QCSkuStandardRevision.sku_id == QCSkuItem.id)
            & (QCSkuStandardRevision.tenant_id == tenant_id)
            & (QCSkuStandardRevision.status == "active"),
        )
        .filter(
            QCSkuItem.tenant_id == tenant_id,
            QCSkuItem.status.in_(("active", "confirmed", "published", "installed")),
        )
    )
    term = q.strip()
    if term:
        escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.filter(
            QCSkuItem.item_number.ilike(pattern, escape="\\")
            | QCSkuItem.name.ilike(pattern, escape="\\")
        )
    rows = query.distinct().order_by(QCSkuItem.item_number).limit(50).all()
    items = []
    for sku in rows:
        photo = (
            db.query(QCStandardPhoto)
            .filter_by(sku_id=sku.id, tenant_id=tenant_id)
            .order_by(QCStandardPhoto.is_primary.desc(), QCStandardPhoto.created_at)
            .first()
        )
        items.append(
            {
                "id": sku.id,
                "item_number": sku.item_number,
                "name": sku.name,
                "reference_image_url": photo.image_url if photo else None,
                "standard_photo_path": photo.local_path if photo else None,
            }
        )
    return JSONResponse({"items": items})


def _pad_job(db: Session, job_id: str, tenant_id: str):
    from src.db.execution_models import QCInspectionJob

    return db.query(QCInspectionJob).filter_by(id=job_id, tenant_id=tenant_id).first()


@router.get("/api/v1/pad/inspection-jobs/{job_id}")
async def pad_inspection_job_state(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")
    job = _pad_job(db, job_id, tenant_id)
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)

    from src.db.execution_models import QCCheckpointResult
    from src.inspection.service import get_active_detection_points_for_job

    points = get_active_detection_points_for_job(db, job_id, tenant_id=tenant_id)
    existing = {
        row.detection_point_id: row
        for row in db.query(QCCheckpointResult).filter_by(job_id=job_id, tenant_id=tenant_id).all()
    }
    return JSONResponse(
        {
            "id": job.id,
            "sku_id": job.sku_id,
            "status": job.status,
            "active_standard_revision_id": job.active_standard_revision_id,
            "checkpoints": [
                {
                    "id": point.id,
                    "point_code": point.point_code,
                    "label": point.label,
                    "description": point.description,
                    "severity": point.severity,
                    "submitted_result": existing[point.id].result if point.id in existing else None,
                }
                for point in points
            ],
            "media_count": len(job.media),
            "final_report": (
                {
                    "overall_result": job.final_report.overall_result,
                    "summary_text": job.final_report.summary_text,
                }
                if job.final_report
                else None
            ),
        }
    )


@router.post("/api/v1/pad/inspection-jobs/{job_id}/media")
async def pad_attach_inspection_media(
    request: Request,
    job_id: str,
    image: UploadFile = File(...),
    capture_source: str = Form(default="fixture_upload"),
    db: Session = Depends(get_db_dep),
):
    """Validate and persist a Stage 2 Mac capture against a real inspection job."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")
    job = _pad_job(db, job_id, tenant_id)
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)
    if capture_source not in {"fixture_upload", "mac_usb_camera"}:
        return JSONResponse({"error": "unsupported capture_source"}, status_code=400)

    from uuid import uuid4

    from src.inspection.api_service import attach_inspection_media
    from src.storage.local_storage import get_inspection_dir
    from src.storage.upload_validation import UploadValidationError, read_and_validate_upload

    try:
        validated = await read_and_validate_upload(image)
    except UploadValidationError as exc:
        return JSONResponse({"error": exc.message}, status_code=exc.status_code)
    capture_dir = get_inspection_dir(tenant_id, job.sku_id, job.id) / "captures"
    capture_dir.mkdir(parents=True, exist_ok=True)
    destination = capture_dir / f"{capture_source}-{uuid4().hex}{validated.extension}"
    destination.write_bytes(validated.content)
    media = attach_inspection_media(
        db,
        job_id=job.id,
        local_path=str(destination),
        sha256=validated.sha256,
        mime_type=validated.mime_type,
        view_type=capture_source,
        tenant_id=tenant_id,
    )
    return JSONResponse(
        {
            "status": "attached",
            "media_id": media.id,
            "sha256": validated.sha256,
            "size_bytes": validated.size_bytes,
            "source": capture_source,
        },
        status_code=201,
    )


@router.post("/api/v1/pad/inspection-jobs/{job_id}/vision-analyze")
async def pad_run_vision_analysis(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    """Run the configured live vision assistant and return reviewable suggestions."""
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")
    job = _pad_job(db, job_id, tenant_id)
    if job is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)
    if job.final_report is not None:
        return JSONResponse({"error": "inspection job already finalized"}, status_code=409)

    from src.db.execution_models import QCInspectionMedia, QCModelResult
    from src.cv_preanalysis import PreanalysisError, run_preanalysis, write_evidence
    from src.inspection.service import get_active_detection_points_for_job
    from src.qc_model.studio import ai_gateway

    media = (
        db.query(QCInspectionMedia)
        .filter_by(job_id=job.id, tenant_id=tenant_id)
        .order_by(QCInspectionMedia.created_at.desc())
        .first()
    )
    if media is None or not media.local_path:
        return JSONResponse({"error": "inspection job has no local image evidence"}, status_code=400)
    image_path = Path(media.local_path)
    if not image_path.is_file():
        return JSONResponse({"error": "inspection image evidence is unavailable"}, status_code=409)

    points = get_active_detection_points_for_job(db, job.id, tenant_id=tenant_id)
    checkpoint_contract = [
        {
            "point_code": point.point_code,
            "label": point.label,
            "description": point.description,
            "method_hint": point.method_hint,
            "expected_value": point.expected_value,
            "pass_criteria": point.pass_criteria,
            "expected_features": point.expected_features_json or {},
            "cv_config": point.cv_config_json or {},
        }
        for point in points
    ]

    cv_started = time.monotonic()
    cv_records: list[dict[str, Any]] = []
    cv_prompt_points: list[dict[str, Any]] = []
    evidence_root = image_path.parent / "cv-evidence"
    for point in points:
        config = point.cv_config_json or {}
        if not config:
            cv_records.append({
                "point_code": point.point_code,
                "cv_status": "not_configured",
                "analysis": None,
                "evidence_path": None,
            })
            continue
        try:
            analysis = run_preanalysis(
                image_path,
                config,
                point.expected_features_json or {},
            )
            evidence_path = write_evidence(
                evidence_root,
                request_id=job.id,
                point_code=point.point_code,
                analysis=analysis,
            )
        except PreanalysisError as exc:
            # WS8 failure semantics: CV is evidence, never the final judge.
            # Record the failure and continue to the VLM without this point's
            # CV context; operator review remains mandatory downstream.
            cv_records.append({
                "point_code": point.point_code,
                "cv_status": "failed",
                "error": str(exc)[:500],
                "analysis": None,
                "evidence_path": None,
            })
            continue
        record = {
            "point_code": point.point_code,
            "cv_status": "completed",
            "analysis": analysis,
            "evidence_path": evidence_path,
        }
        cv_records.append(record)
        cv_prompt_points.append({
            "point_code": point.point_code,
            "analysis": analysis,
        })
    cv_context = None
    if cv_prompt_points:
        cv_context = {
            "schema_version": "1.0",
            "points": cv_prompt_points,
            "verdict_effect": "informational_only",
        }
    fallback_crops, crop_metadata = _write_fallback_crops(
        image_path, job_id=job.id, points=points, cv_records=cv_records,
    )
    cv_elapsed_ms = int((time.monotonic() - cv_started) * 1000)
    try:
        result = ai_gateway.inspect_image(
            image_path=image_path,
            mime_type=media.mime_type or "",
            language=resolve_language(request),
            checkpoints=checkpoint_contract,
            cv_context=cv_context,
            fallback_crops=fallback_crops,
        )
    except ai_gateway.StudioAIError as exc:
        return JSONResponse({"error": str(exc)}, status_code=502)

    point_ids = {point.point_code: point.id for point in points}
    suggestions = [
        {**item, "detection_point_id": point_ids[item["point_code"]]}
        for item in result["checkpoint_results"]
    ]
    raw_output = {
        "summary": result["summary"],
        "checkpoint_results": result["checkpoint_results"],
        "incidental_findings": [],
        "mode": "operator_review_suggestions",
        "cv_preanalysis": cv_records,
        "fallback_crops": crop_metadata,
        "routing": result.get("routing"),
        "assistant": result["assistant"],
        "timings_ms": {
            "cv": cv_elapsed_ms,
            "vision_total": result["assistant"]["elapsed_ms"],
        },
    }
    from uuid import uuid4
    model_result = QCModelResult(
        id=uuid4().hex,
        job_id=job.id,
        tenant_id=tenant_id,
        media_id=media.id,
        provider=result["assistant"]["provider"],
        model_name=result["assistant"]["model"],
        http_status=200,
        elapsed_ms=result["assistant"]["elapsed_ms"],
        raw_output=raw_output,
    )
    db.add(model_result)
    db.commit()
    return JSONResponse({
        "status": "vision_suggestions_ready",
        "model_result_id": model_result.id,
        "summary": result["summary"],
        "checkpoint_results": suggestions,
        "assistant": result["assistant"],
        "cv_preanalysis": cv_records,
        "fallback_crops": crop_metadata,
        "timings_ms": raw_output["timings_ms"],
        "operator_review_required": True,
    })


@router.post("/api/v1/pad/inspection-jobs/{job_id}/checkpoint-results")
async def pad_submit_checkpoint_batch(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")
    if _pad_job(db, job_id, tenant_id) is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)
    body = await request.json()
    results = body.get("results")
    if not isinstance(results, list):
        return JSONResponse({"error": "results must be an array"}, status_code=400)
    from src.inspection.service import submit_checkpoint_results_batch

    try:
        rows = submit_checkpoint_results_batch(db, job_id, results, tenant_id=tenant_id)
    except (ValueError, TypeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(
        {
            "status": "checkpoint_results_recorded",
            "count": len(rows),
            "operator_id": operator_id,
        }
    )


@router.post("/api/v1/pad/inspection-jobs/{job_id}/finalize")
async def pad_finalize_inspection_job(
    request: Request,
    job_id: str,
    db: Session = Depends(get_db_dep),
):
    operator_id = _require_operator(request)
    if operator_id is None:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    tenant_id = request.session.get("tenant_id", "demo")
    if _pad_job(db, job_id, tenant_id) is None:
        return JSONResponse({"error": "inspection job not found"}, status_code=404)
    from src.inspection.api_service import finalize_inspection_job

    try:
        report = finalize_inspection_job(db, job_id, tenant_id=tenant_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(
        {
            "status": "finalized",
            "overall_result": report.overall_result,
            "checkpoint_results_count": report.checkpoint_results_count,
            "findings_count": report.findings_count,
            "summary_text": report.summary_text,
        }
    )
