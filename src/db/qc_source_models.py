"""SQLAlchemy models for the QC Source Ingestion Workbench (PR 21).

Registers, extracts from, and drafts fragments out of QC *source materials*
(drawings, specs, standards, samples, natural-language / speech input).

Safety invariants baked into this layer:
- Every entity is tenant-scoped (``tenant_id`` column; queries always filter it).
- Append-safe / auditable: a new extraction run creates a NEW
  ``SourceExtractionJob`` plus NEW fragments/drafts. It never mutates prior
  extraction output.
- There is NO ``active`` status here. Everything is ``draft`` / ``reviewed`` /
  ``rejected``. Activation only happens later via the Training Pack apply path
  (a different PR). Nothing in this module can update a Training Pack.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow

# Draft-lifecycle statuses shared by source docs, fragments, and drafts.
# NOTE: there is intentionally no activation status at this layer.
SOURCE_STATUS_DRAFT = "draft"
SOURCE_STATUS_REVIEWED = "reviewed"
SOURCE_STATUS_REJECTED = "rejected"


class QCSourceDocument(Base):
    """A registered piece of QC source material (text / file ref / image ref)."""

    __tablename__ = "qc_source_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # One of QCSourceType (validated at the API boundary).
    source_type: Mapped[str] = mapped_column(String(48), nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(256))
    # Inline text content for natural_language / process_spec / inspection_standard.
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    # Reference to an already-stored file/image (URL or local path) — this PR
    # does not build new file storage; it only records references.
    file_ref: Mapped[Optional[str]] = mapped_column(String(1024))
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    # draft | reviewed | rejected  (never "active")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SOURCE_STATUS_DRAFT)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class SourceExtractionJob(Base):
    """Tracks one extraction run over a source document."""

    __tablename__ = "qc_source_extraction_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    source_id: Mapped[str] = mapped_column(
        ForeignKey("qc_source_documents.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    fragment_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class QCSourceFragment(Base):
    """An extracted candidate unit derived from a source document."""

    __tablename__ = "qc_source_fragments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    source_id: Mapped[str] = mapped_column(
        ForeignKey("qc_source_documents.id"), nullable=False, index=True
    )
    extraction_job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_source_extraction_jobs.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # One of FragmentType (see src.qc_model.ingestion.types).
    fragment_type: Mapped[str] = mapped_column(String(48), nullable=False)
    # UI grouping hint: detection_point | boundary_rule | review
    candidate_label: Mapped[str] = mapped_column(String(32), nullable=False, default="review")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[Optional[str]] = mapped_column(Text)
    source_excerpt: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # draft | reviewed | rejected  (never "active")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SOURCE_STATUS_DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class QCRequirementDraft(Base):
    """A draft requirement derived from a fragment — NOT an active rule."""

    __tablename__ = "qc_requirement_drafts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("qc_source_documents.id"), nullable=False, index=True)
    extraction_job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_source_extraction_jobs.id"), nullable=False, index=True
    )
    fragment_id: Mapped[str] = mapped_column(ForeignKey("qc_source_fragments.id"), nullable=False, index=True)
    draft_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Suggested checkpoint category (proposed only — supervisor decides later).
    proposed_checkpoint_category: Mapped[Optional[str]] = mapped_column(String(48))
    # draft | reviewed | rejected  (never "active")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SOURCE_STATUS_DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class QCBoundaryDraft(Base):
    """A draft physical/rule boundary derived from a fragment — NOT an active rule."""

    __tablename__ = "qc_boundary_drafts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("qc_source_documents.id"), nullable=False, index=True)
    extraction_job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_source_extraction_jobs.id"), nullable=False, index=True
    )
    fragment_id: Mapped[str] = mapped_column(ForeignKey("qc_source_fragments.id"), nullable=False, index=True)
    boundary_text: Mapped[str] = mapped_column(Text, nullable=False)
    # physical_measurement | rule_verification (advisory, not enforced here)
    boundary_kind: Mapped[Optional[str]] = mapped_column(String(48))
    # draft | reviewed | rejected  (never "active")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=SOURCE_STATUS_DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
