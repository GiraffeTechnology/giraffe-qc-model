"""API + UI for the QC Source Ingestion Workbench (PR 21 §4, §6).

Extends the existing FastAPI + Jinja2 admin app. All endpoints are
tenant-scoped and reuse the existing ``get_db_dep`` dependency. Nothing here
writes to a Training Pack table or creates an active rule — everything is a
draft fragment.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.authz import effective_tenant
from src.api.deps import get_db_dep
from src.api.uploads import validate_safe_id
from src.qc_model.ingestion import service
from src.qc_model.ingestion.process_card import REAL_TEXT_EXTRACTION_EXTENSIONS
from src.qc_model.ingestion.types import FragmentType, QCSourceType, is_valid_source_type
from src.storage.upload_validation import (
    UploadValidationError,
    read_and_validate_document_upload,
)

router = APIRouter(tags=["qc-source-ingestion"])

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
_SOURCE_UPLOAD_DIR = Path("data/qc_source_uploads")


# ── Request bodies ────────────────────────────────────────────────────────


class CreateSourceBody(BaseModel):
    source_type: str
    tenant_id: str = "default"
    sku_id: Optional[str] = None
    title: Optional[str] = None
    text_content: Optional[str] = None
    file_ref: Optional[str] = None
    mime_type: Optional[str] = None
    metadata_json: Optional[dict] = None
    created_by: Optional[str] = None


class ExtractBody(BaseModel):
    tenant_id: str = "default"


class ReviewSourceBody(BaseModel):
    decision: str  # "reviewed" | "rejected"
    tenant_id: str = "default"
    reviewer: Optional[str] = None


# ── Views ─────────────────────────────────────────────────────────────────


def _source_view(doc) -> dict:
    return {
        "source_id": doc.id,
        "tenant_id": doc.tenant_id,
        "training_pack_id": doc.training_pack_id,
        "sku_id": doc.sku_id,
        "source_type": doc.source_type,
        "title": doc.title,
        "text_content": doc.text_content,
        "file_ref": doc.file_ref,
        "mime_type": doc.mime_type,
        "status": doc.status,
    }


def _job_view(job) -> dict:
    return {
        "job_id": job.id,
        "tenant_id": job.tenant_id,
        "source_id": job.source_id,
        "training_pack_id": job.training_pack_id,
        "status": job.status,
        "provider": job.provider,
        "fragment_count": job.fragment_count,
        "error_message": job.error_message,
    }


def _fragment_view(frag) -> dict:
    return {
        "fragment_id": frag.id,
        "fragment_type": frag.fragment_type,
        "candidate_label": frag.candidate_label,
        "text": frag.text,
        "rationale": frag.rationale,
        "source_excerpt": frag.source_excerpt,
        "confidence": frag.confidence,
        "status": frag.status,
    }


# ── JSON API ──────────────────────────────────────────────────────────────


@router.post("/api/qc/training-packs/{training_pack_id}/sources", status_code=201)
def create_source(
    training_pack_id: str,
    body: CreateSourceBody,
    db: Session = Depends(get_db_dep),
):
    if not is_valid_source_type(body.source_type):
        raise HTTPException(status_code=422, detail=f"Invalid source_type: {body.source_type!r}")
    try:
        doc = service.create_source_document(
            db,
            training_pack_id=training_pack_id,
            source_type=body.source_type,
            tenant_id=body.tenant_id,
            sku_id=body.sku_id,
            title=body.title,
            text_content=body.text_content,
            file_ref=body.file_ref,
            mime_type=body.mime_type,
            metadata_json=body.metadata_json,
            created_by=body.created_by,
        )
    except service.CrossTenantTrainingPack as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidSourceType as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _source_view(doc)


@router.get("/api/qc/training-packs/{training_pack_id}/sources")
def list_sources(
    training_pack_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    docs = service.list_source_documents(db, training_pack_id, tenant_id)
    return {"training_pack_id": training_pack_id, "sources": [_source_view(d) for d in docs]}


@router.get("/api/qc/sources/{source_id}")
def get_source(
    source_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    try:
        doc = service.get_source_document(db, source_id, tenant_id)
    except service.SourceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _source_view(doc)


@router.post("/api/qc/sources/{source_id}/review")
def review_source(
    source_id: str,
    body: ReviewSourceBody,
    db: Session = Depends(get_db_dep),
):
    try:
        doc = service.review_source_document(
            db, source_id, decision=body.decision, tenant_id=body.tenant_id, reviewer=body.reviewer,
        )
    except service.SourceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.InvalidReviewDecision as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _source_view(doc)


@router.post("/api/qc/sources/{source_id}/extract", status_code=201)
def extract_source(
    source_id: str,
    body: ExtractBody = ExtractBody(),
    db: Session = Depends(get_db_dep),
):
    try:
        job = service.run_extraction(db, source_id, body.tenant_id)
    except service.SourceNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _job_view(job)


@router.get("/api/qc/source-extraction-jobs/{job_id}")
def get_job(
    job_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    try:
        job = service.get_extraction_job(db, job_id, tenant_id)
    except service.ExtractionJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _job_view(job)


@router.get("/api/qc/source-extraction-jobs/{job_id}/fragments")
def get_job_fragments(
    job_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    try:
        fragments = service.list_job_fragments(db, job_id, tenant_id)
    except service.ExtractionJobNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job_id, "fragments": [_fragment_view(f) for f in fragments]}


# ── UI (extends existing admin UI) ────────────────────────────────────────


def _render_panel(request: Request, training_pack_id: str, tenant_id: str, db: Session):
    docs = service.list_source_documents(db, training_pack_id, tenant_id)
    source_rows = []
    for doc in docs:
        # Show fragments from the latest extraction job for this source, grouped.
        from src.db.qc_source_models import QCSourceFragment, SourceExtractionJob

        latest_job = (
            db.query(SourceExtractionJob)
            .filter_by(source_id=doc.id, tenant_id=tenant_id, status="completed")
            .order_by(SourceExtractionJob.created_at.desc())
            .first()
        )
        grouped: dict[str, list] = {}
        if latest_job:
            from src.api.qc_authoring_router import proposal_view
            from src.db.qc_learning_models import QCLearnedDetectionPointProposal

            frags = (
                db.query(QCSourceFragment)
                .filter_by(extraction_job_id=latest_job.id, tenant_id=tenant_id)
                .all()
            )
            for f in frags:
                fv = _fragment_view(f)
                # Attach any authored rule proposals for this fragment (PR 22).
                authored = (
                    db.query(QCLearnedDetectionPointProposal)
                    .filter_by(source_fragment_id=f.id, tenant_id=tenant_id)
                    .order_by(QCLearnedDetectionPointProposal.created_at.desc())
                    .all()
                )
                fv["proposals"] = [proposal_view(p) for p in authored]
                grouped.setdefault(f.fragment_type, []).append(fv)
        source_rows.append(
            {
                "source": _source_view(doc),
                "grouped_fragments": grouped,
                "latest_job": _job_view(latest_job) if latest_job else None,
            }
        )
    return templates.TemplateResponse(
        request,
        "qc_source_panel.html",
        context={
            "training_pack_id": training_pack_id,
            "tenant_id": tenant_id,
            "source_types": [t.value for t in QCSourceType],
            "fragment_types": [t.value for t in FragmentType],
            "source_rows": source_rows,
        },
    )


@router.get("/admin/qc-model/training-packs/{training_pack_id}/sources", response_class=HTMLResponse)
def sources_panel(
    request: Request,
    training_pack_id: str,
    tenant_id: str = "default",
    db: Session = Depends(get_db_dep),
):
    return _render_panel(request, training_pack_id, tenant_id, db)


def _sources_redirect(training_pack_id: str, tenant_id: str) -> RedirectResponse:
    suffix = f"?tenant_id={tenant_id}" if tenant_id and tenant_id != "default" else ""
    return RedirectResponse(
        url=f"/admin/qc-model/training-packs/{training_pack_id}/sources{suffix}", status_code=303
    )


@router.post("/admin/qc-model/training-packs/{training_pack_id}/sources")
def ui_create_source(
    training_pack_id: str,
    source_type: str = Form(...),
    title: str = Form(""),
    text_content: str = Form(""),
    file_ref: str = Form(""),
    tenant_id: str = Form("default"),
    db: Session = Depends(get_db_dep),
):
    if is_valid_source_type(source_type):
        try:
            service.create_source_document(
                db,
                training_pack_id=training_pack_id,
                source_type=source_type,
                tenant_id=tenant_id,
                title=title or None,
                text_content=text_content or None,
                file_ref=file_ref or None,
            )
        except service.CrossTenantTrainingPack:
            pass
    return _sources_redirect(training_pack_id, tenant_id)


@router.post("/admin/qc-model/training-packs/{training_pack_id}/sources/upload")
async def ui_upload_process_card(
    training_pack_id: str,
    request: Request,
    title: str = Form(""),
    tenant_id: str = Form("default"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db_dep),
):
    """Real process-card file upload (replaces the file_ref text field for
    this flow -- file_ref is still accepted separately in the plain
    ``sources`` form above for callers that already have a stored reference).

    Stores the file, then creates a ``process_card`` source document whose
    ``file_ref`` points at the stored path. For the narrow set of formats
    this environment can actually decode as plain text
    (:data:`REAL_TEXT_EXTRACTION_EXTENSIONS`), the decoded text is stored as
    ``text_content`` too so extraction (a separate, later step) has real
    text to work with -- not fabricated. Everything else (PDF/DOCX/images/
    CAD) is stored and classified, but extraction will honestly report that
    no parser is wired rather than guess.
    """
    tenant_id = effective_tenant(request, tenant_id)
    validate_safe_id(training_pack_id, "training_pack_id")

    try:
        validated = await read_and_validate_document_upload(file, filename=file.filename or "")
    except UploadValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    dest_dir = _SOURCE_UPLOAD_DIR / tenant_id / training_pack_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    stored_name = f"{uuid.uuid4().hex}{validated.extension}"
    dest_path = dest_dir / stored_name
    dest_path.write_bytes(validated.content)

    text_content = None
    if validated.extension in REAL_TEXT_EXTRACTION_EXTENSIONS:
        try:
            text_content = validated.content.decode("utf-8")
        except UnicodeDecodeError:
            # Extension claimed plain text but the bytes aren't valid UTF-8 --
            # leave text_content unset rather than store mojibake; extraction
            # will honestly report no usable text was recovered.
            text_content = None

    try:
        service.create_source_document(
            db,
            training_pack_id=training_pack_id,
            source_type=QCSourceType.PROCESS_CARD.value,
            tenant_id=tenant_id,
            title=title or file.filename,
            text_content=text_content,
            file_ref=str(dest_path),
            mime_type=file.content_type,
        )
    except service.CrossTenantTrainingPack:
        pass
    return _sources_redirect(training_pack_id, tenant_id)


@router.post("/admin/qc-model/training-packs/{training_pack_id}/sources/{source_id}/extract")
def ui_extract_source(
    training_pack_id: str,
    source_id: str,
    tenant_id: str = Form("default"),
    db: Session = Depends(get_db_dep),
):
    try:
        service.run_extraction(db, source_id, tenant_id)
    except service.SourceNotFound:
        pass
    return _sources_redirect(training_pack_id, tenant_id)


@router.post("/admin/qc-model/training-packs/{training_pack_id}/sources/{source_id}/review")
def ui_review_source(
    training_pack_id: str,
    source_id: str,
    decision: str = Form(...),
    tenant_id: str = Form("default"),
    reviewer: str = Form("qc_supervisor"),
    db: Session = Depends(get_db_dep),
):
    try:
        service.review_source_document(
            db, source_id, decision=decision, tenant_id=tenant_id, reviewer=reviewer,
        )
    except (service.SourceNotFound, service.InvalidReviewDecision):
        pass
    suffix = f"?tenant_id={tenant_id}" if tenant_id and tenant_id != "default" else ""
    return RedirectResponse(
        url=f"/admin/qc-model/training-packs/{training_pack_id}/sources{suffix}", status_code=303
    )
