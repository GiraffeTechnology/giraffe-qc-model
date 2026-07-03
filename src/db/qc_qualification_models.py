"""SQLAlchemy models for qualification, shadow mode, and the accuracy gate (PR 27).

Qualification converts production confidence from a code claim into a measured,
auditable report. Only after an approved qualification report that meets the
false-pass / false-fail / sample-count thresholds can a Training Pack reach L3
``controlled_active`` (the readiness gate consults this layer).

Safety invariants:
- Every entity is tenant-scoped.
- ``QualificationApproval`` is append-only audit; a report is **immutable once
  approved** (no re-run/edit that mutates an approved report).
- False pass is treated as critical (default max false-pass rate = 0).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow

# Ground-truth human labels for a qualification sample.
LABEL_PASS = "pass"
LABEL_FAIL = "fail"
VALID_LABELS = {LABEL_PASS, LABEL_FAIL}

# Report / approval lifecycle.
REPORT_DRAFT = "draft"
REPORT_APPROVED = "approved"
REPORT_REJECTED = "rejected"

APPROVAL_APPROVED = "approved"
APPROVAL_REJECTED = "rejected"
VALID_APPROVAL_DECISIONS = {APPROVAL_APPROVED, APPROVAL_REJECTED}


class QualificationDataset(Base):
    __tablename__ = "qc_qualification_datasets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    station_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(256))
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class QualificationSample(Base):
    __tablename__ = "qc_qualification_samples"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("qc_qualification_datasets.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # reference | positive | defect | boundary | capture_artifact
    sample_type: Mapped[str] = mapped_column(String(32), nullable=False)
    image_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    # Ground-truth human label: pass | fail
    human_label: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class QualificationRun(Base):
    __tablename__ = "qc_qualification_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("qc_qualification_datasets.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    # running | completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class QualificationResult(Base):
    """Per-detection-point metrics for one qualification run."""

    __tablename__ = "qc_qualification_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    run_id: Mapped[str] = mapped_column(
        ForeignKey("qc_qualification_runs.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    defect_sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    boundary_sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    true_pass: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    true_fail: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    false_pass: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    false_fail: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    indeterminate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    false_pass_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    false_fail_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    confusion_json: Mapped[Optional[dict]] = mapped_column(JSON)
    meets_thresholds: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    threshold_failures_json: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class QualificationReport(Base):
    __tablename__ = "qc_qualification_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    run_id: Mapped[str] = mapped_column(
        ForeignKey("qc_qualification_runs.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    overall_meets_thresholds: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    qualified_detection_point_codes_json: Mapped[Optional[list]] = mapped_column(JSON)
    thresholds_json: Mapped[Optional[dict]] = mapped_column(JSON)
    summary_json: Mapped[Optional[dict]] = mapped_column(JSON)
    # draft | approved | rejected
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=REPORT_DRAFT)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class QualificationApproval(Base):
    """Append-only supervisor sign-off on a qualification report (audit)."""

    __tablename__ = "qc_qualification_approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    report_id: Mapped[str] = mapped_column(
        ForeignKey("qc_qualification_reports.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # approved | rejected
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ShadowObservation(Base):
    """L1 shadow-mode record: model output vs. human QC decision (no effect on pass/reject)."""

    __tablename__ = "qc_shadow_observations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    image_reference: Mapped[Optional[str]] = mapped_column(String(1024))
    model_disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    human_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    agrees: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
