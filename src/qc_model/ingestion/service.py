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

from src.db.qc_learning_models import QCLearningJob
from src.db.qc_source_models import (
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


class CrossTenantTrainingPack(ValueError):
    """A training_pack_id already owned by another tenant."""


# ── Tenant / ownership guards ─────────────────────────────────────────────


def _training_pack_owners(db: Session, training_pack_id: str) -> set[str]:
    """Return the set of tenant_ids that already reference this training pack.

    There is no Training Pack registry table, so ownership is derived from
    existing rows that reference the id (learning jobs and source documents).
    """
    owners: set[str] = set()
    owners.update(
        r[0]
        for r in db.query(QCLearningJob.tenant_id)
        .filter(QCLearningJob.training_pack_id == training_pack_id)
        .all()
    )
    owners.update(
        r[0]
        for r in db.query(QCSourceDocument.tenant_id)
        .filter(QCSourceDocument.training_pack_id == training_pack_id)
        .all()
    )
    return owners


def assert_training_pack_accessible(db: Session, training_pack_id: str, tenant_id: str) -> None:
    """Raise CrossTenantTrainingPack if the pack is owned by another tenant.

    First use by a tenant binds the id to that tenant. If it is already known
    only under other tenants, this tenant may not reference it.
    """
    owners = _training_pack_owners(db, training_pack_id)
    if owners and tenant_id not in owners:
        raise CrossTenantTrainingPack(
            f"training_pack_id {training_pack_id!r} is not accessible for tenant {tenant_id!r}"
        )


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
