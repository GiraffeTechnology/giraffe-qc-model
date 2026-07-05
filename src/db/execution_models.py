"""SQLAlchemy models for QC inspection execution pipeline."""
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow


class QCInspectionJob(Base):
    """One inspection run for a production unit against the active SKU standard."""
    __tablename__ = "qc_inspection_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("qc_sku_items.id"), nullable=False, index=True)
    # Snapshot of the active standard revision at job creation time.
    active_standard_revision_id: Mapped[str] = mapped_column(
        ForeignKey("qc_sku_standard_revisions.id"), nullable=False, index=True
    )
    job_ref: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    # pending | running | pass | fail | review_required | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    standard_revision: Mapped["src.db.sku_models.QCSkuStandardRevision"] = relationship(  # type: ignore[name-defined]
        "QCSkuStandardRevision", foreign_keys=[active_standard_revision_id]
    )
    media: Mapped[list["QCInspectionMedia"]] = relationship(
        "QCInspectionMedia", back_populates="job", cascade="all, delete-orphan"
    )
    model_results: Mapped[list["QCModelResult"]] = relationship(
        "QCModelResult", back_populates="job", cascade="all, delete-orphan"
    )
    checkpoint_results: Mapped[list["QCCheckpointResult"]] = relationship(
        "QCCheckpointResult", back_populates="job", cascade="all, delete-orphan"
    )
    incidental_findings: Mapped[list["QCIncidentalFinding"]] = relationship(
        "QCIncidentalFinding", back_populates="job", cascade="all, delete-orphan"
    )
    final_report: Mapped[Optional["QCFinalReport"]] = relationship(
        "QCFinalReport", back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    human_reviews: Mapped[list["QCHumanReview"]] = relationship(
        "QCHumanReview", back_populates="job", cascade="all, delete-orphan"
    )


class QCInspectionMedia(Base):
    """Production image submitted for an inspection job."""
    __tablename__ = "qc_inspection_media"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("qc_inspection_jobs.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(512))
    local_path: Mapped[Optional[str]] = mapped_column(String(512))
    angle: Mapped[Optional[str]] = mapped_column(String(64))
    view_type: Mapped[Optional[str]] = mapped_column(String(64))
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    width_px: Mapped[Optional[int]] = mapped_column(Integer)
    height_px: Mapped[Optional[int]] = mapped_column(Integer)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    job: Mapped["QCInspectionJob"] = relationship("QCInspectionJob", back_populates="media")


class QCModelResult(Base):
    """Raw output from a vision model call within an inspection job."""
    __tablename__ = "qc_model_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("qc_inspection_jobs.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    media_id: Mapped[Optional[str]] = mapped_column(ForeignKey("qc_inspection_media.id"), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    http_status: Mapped[Optional[int]] = mapped_column(Integer)
    elapsed_ms: Mapped[Optional[int]] = mapped_column(Integer)
    raw_output: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    job: Mapped["QCInspectionJob"] = relationship("QCInspectionJob", back_populates="model_results")
    media: Mapped[Optional["QCInspectionMedia"]] = relationship("QCInspectionMedia")


class QCCheckpointResult(Base):
    """Result for a single detection-point checkpoint within a job.

    No-guess policy: every active detection point for the job's standard revision
    must have exactly one entry.  result values of 'not_visible' or 'low_confidence'
    cannot contribute to a pass verdict.
    """
    __tablename__ = "qc_checkpoint_results"
    __table_args__ = (
        UniqueConstraint("job_id", "detection_point_id", name="uq_checkpoint_result_job_point"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("qc_inspection_jobs.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_id: Mapped[str] = mapped_column(
        ForeignKey("qc_detection_points.id"), nullable=False, index=True
    )
    model_result_id: Mapped[Optional[str]] = mapped_column(ForeignKey("qc_model_results.id"), index=True)
    # pass | fail | not_visible | low_confidence | missing
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_value: Mapped[Optional[str]] = mapped_column(String(256))
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    job: Mapped["QCInspectionJob"] = relationship("QCInspectionJob", back_populates="checkpoint_results")
    detection_point: Mapped["src.db.sku_models.QCDetectionPoint"] = relationship(  # type: ignore[name-defined]
        "QCDetectionPoint"
    )
    model_result: Mapped[Optional["QCModelResult"]] = relationship("QCModelResult")


class QCIncidentalFinding(Base):
    """An observed defect or anomaly not tied to a named checkpoint."""
    __tablename__ = "qc_incidental_findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("qc_inspection_jobs.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # minor | major | critical
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="minor")
    location_hint: Mapped[Optional[str]] = mapped_column(String(256))
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    job: Mapped["QCInspectionJob"] = relationship("QCInspectionJob", back_populates="incidental_findings")


class QCFinalReport(Base):
    """Computed final verdict for a completed inspection job."""
    __tablename__ = "qc_final_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_inspection_jobs.id"), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # pass | fail | review_required
    overall_result: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_text: Mapped[Optional[str]] = mapped_column(Text)
    checkpoint_results_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    findings_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    job: Mapped["QCInspectionJob"] = relationship("QCInspectionJob", back_populates="final_report")


class QCHumanReview(Base):
    """Human override decision on a job that reached review_required."""
    __tablename__ = "qc_human_reviews"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("qc_inspection_jobs.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reviewer_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # approve | reject | escalate
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    job: Mapped["QCInspectionJob"] = relationship("QCInspectionJob", back_populates="human_reviews")


class QCAuditEvent(Base):
    """Immutable append-only audit trail for SKU standard and job lifecycle changes."""
    __tablename__ = "qc_audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # sku | standard_revision | job
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # created | confirmed | archived | superseded | job_started | job_finalized | human_review
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor: Mapped[Optional[str]] = mapped_column(String(128))
    details_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
