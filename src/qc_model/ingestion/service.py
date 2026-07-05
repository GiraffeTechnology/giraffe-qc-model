"""Source ingestion service layer (PR 21 §4, §5, §7).

All reads/writes are tenant-scoped. Extraction is append-safe: each run creates
a NEW job + NEW fragments/drafts and never mutates prior output. Nothing here
writes to a Training Pack table.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.db.qc_source_models import (
    SOURCE_STATUS_REJECTED,
    SOURCE_STATUS_REVIEWED,
    QCBoundaryDraft,
    QCRequirementDraft,
    QCSourceDocument,
    QCSourceFragment,
    SourceExtractionJob,
)
from src.qc_model.ingestion.extractor import extract
from src.qc_model.ingestion.types import is_valid_source_type


def _uid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SourceNotFound(ValueError):
    pass


class ExtractionJobNotFound(ValueError):
    pass


class InvalidSourceType(ValueError):
    pass


class InvalidReviewDecision(ValueError):
    pass


# The unified ownership resolver is the single source of truth (§4.4). The
# name is re-exported here for backward compatibility with existing callers.
from src.qc_model.training_pack.ownership import (  # noqa: E402
    CrossTenantTrainingPack,
    assert_pack_accessible,
    pack_owner_tenants as _training_pack_owners,
)


# ── Tenant / ownership guards ─────────────────────────────────────────────


def assert_training_pack_accessible(db: Session, training_pack_id: str, tenant_id: str) -> None:
    """Raise CrossTenantTrainingPack if the pack is owned by another tenant."""
    assert_pack_accessible(db, training_pack_id, tenant_id)


# ── Source documents ──────────────────────────────────────────────────────


def create_source_document(
    db: Session,
    training_pack_id: str,
    source_type: str,
    tenant_id: str = "default",
    sku_id: Optional[str] = None,
    title: Optional[str] = None,
    text_content: Optional[str] = None,
    file_ref: Optional[str] = None,
    mime_type: Optional[str] = None,
    metadata_json: Optional[dict] = None,
    created_by: Optional[str] = None,
) -> QCSourceDocument:
    if not is_valid_source_type(source_type):
        raise InvalidSourceType(f"Unrecognized source_type: {source_type!r}")
    assert_training_pack_accessible(db, training_pack_id, tenant_id)

    doc = QCSourceDocument(
        id=_uid(),
        tenant_id=tenant_id,
        training_pack_id=training_pack_id,
        sku_id=sku_id,
        source_type=source_type,
        title=title,
        text_content=text_content,
        file_ref=file_ref,
        mime_type=mime_type,
        metadata_json=metadata_json,
        status="draft",
        created_by=created_by,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_source_document(db: Session, source_id: str, tenant_id: str = "default") -> QCSourceDocument:
    doc = (
        db.query(QCSourceDocument)
        .filter_by(id=source_id, tenant_id=tenant_id)
        .first()
    )
    if doc is None:
        raise SourceNotFound(f"Source {source_id!r} not found")
    return doc


def review_source_document(
    db: Session,
    source_id: str,
    decision: str,
    tenant_id: str = "default",
    reviewer: Optional[str] = None,
) -> QCSourceDocument:
    """Supervisor review of a source document (draft → reviewed | rejected).

    This is the supported human action that clears a source out of the
    readiness gate's "source documents reviewed" check. It only moves a
    source between review states — it never activates anything.
    """
    if decision not in (SOURCE_STATUS_REVIEWED, SOURCE_STATUS_REJECTED):
        raise InvalidReviewDecision(
            f"decision must be {SOURCE_STATUS_REVIEWED!r} or {SOURCE_STATUS_REJECTED!r}, got {decision!r}"
        )
    doc = get_source_document(db, source_id, tenant_id)
    doc.status = decision
    if reviewer:
        # Preserve the original author; record the reviewer in metadata for audit.
        meta = dict(doc.metadata_json or {})
        meta["reviewed_by"] = reviewer
        doc.metadata_json = meta
    db.commit()
    db.refresh(doc)
    return doc


def list_source_documents(
    db: Session, training_pack_id: str, tenant_id: str = "default"
) -> list[QCSourceDocument]:
    return (
        db.query(QCSourceDocument)
        .filter_by(training_pack_id=training_pack_id, tenant_id=tenant_id)
        .order_by(QCSourceDocument.created_at.desc())
        .all()
    )


# ── Extraction ────────────────────────────────────────────────────────────


def run_extraction(db: Session, source_id: str, tenant_id: str = "default") -> SourceExtractionJob:
    """Run the deterministic extractor over a source (append-safe).

    Creates a new SourceExtractionJob and fresh fragments/drafts. Never mutates
    prior jobs/fragments and never writes to a Training Pack table.
    """
    doc = get_source_document(db, source_id, tenant_id)

    job = SourceExtractionJob(
        id=_uid(),
        tenant_id=tenant_id,
        source_id=doc.id,
        training_pack_id=doc.training_pack_id,
        status="running",
        provider=None,
    )
    db.add(job)
    db.commit()

    try:
        output = extract(doc.source_type, doc.text_content, doc.file_ref)
    except Exception as exc:  # fail closed — mark job failed, create nothing.
        job.status = "failed"
        job.error_message = f"{type(exc).__name__}: {exc}"
        job.completed_at = _now()
        db.commit()
        db.refresh(job)
        return job

    job.provider = output.provider
    for frag in output.fragments:
        fragment = QCSourceFragment(
            id=_uid(),
            tenant_id=tenant_id,
            source_id=doc.id,
            extraction_job_id=job.id,
            training_pack_id=doc.training_pack_id,
            fragment_type=frag.fragment_type,
            candidate_label=frag.candidate_label,
            text=frag.text,
            rationale=frag.rationale,
            source_excerpt=frag.source_excerpt,
            confidence=frag.confidence,
            status="draft",
        )
        db.add(fragment)
        db.flush()  # get fragment.id for drafts

        if frag.requirement_draft:
            db.add(
                QCRequirementDraft(
                    id=_uid(),
                    tenant_id=tenant_id,
                    training_pack_id=doc.training_pack_id,
                    source_id=doc.id,
                    extraction_job_id=job.id,
                    fragment_id=fragment.id,
                    draft_text=frag.requirement_draft,
                    proposed_checkpoint_category=frag.requirement_category,
                    status="draft",
                )
            )
        if frag.boundary_draft:
            db.add(
                QCBoundaryDraft(
                    id=_uid(),
                    tenant_id=tenant_id,
                    training_pack_id=doc.training_pack_id,
                    source_id=doc.id,
                    extraction_job_id=job.id,
                    fragment_id=fragment.id,
                    boundary_text=frag.boundary_draft,
                    boundary_kind=frag.boundary_kind,
                    status="draft",
                )
            )

    job.fragment_count = len(output.fragments)
    job.status = "completed"
    job.completed_at = _now()
    db.commit()
    db.refresh(job)
    return job


def get_extraction_job(db: Session, job_id: str, tenant_id: str = "default") -> SourceExtractionJob:
    job = (
        db.query(SourceExtractionJob)
        .filter_by(id=job_id, tenant_id=tenant_id)
        .first()
    )
    if job is None:
        raise ExtractionJobNotFound(f"Extraction job {job_id!r} not found")
    return job


def list_job_fragments(
    db: Session, job_id: str, tenant_id: str = "default"
) -> list[QCSourceFragment]:
    # Verify the job belongs to this tenant first (nested-lookup isolation).
    get_extraction_job(db, job_id, tenant_id)
    return (
        db.query(QCSourceFragment)
        .filter_by(extraction_job_id=job_id, tenant_id=tenant_id)
        .order_by(QCSourceFragment.created_at.asc())
        .all()
    )
