"""SQLAlchemy models for Production Assisted Mode (PR 25).

L2 Production Assisted: a ready Training Pack is used in a real factory-assisted
QC workflow. The model produces a *recommended* disposition and per-detection
evidence; the **final** pass/reject/review decision is always a human one and is
recorded in an append-only audit trail. Nothing here auto-finalizes.

Safety invariants baked into this layer:
- Every entity is tenant-scoped (``tenant_id``; queries always filter it).
- ``ProductionEvidencePacket`` and ``HumanFinalDecision`` are append-only audit
  records (no update/delete via public APIs).
- A run only records *recommended* dispositions; it never writes a final
  pass/reject.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow

# Production modes.
PRODUCTION_MODE_ASSISTED = "production_assisted"

# Recommended dispositions (never a final decision).
DISPOSITION_PASS = "pass_recommended"
DISPOSITION_REJECT = "reject_recommended"
DISPOSITION_REVIEW = "review_required"
DISPOSITION_CAPTURE_RETRY = "capture_retry_required"
DISPOSITION_MEASUREMENT = "measurement_required"
VALID_DISPOSITIONS = {
    DISPOSITION_PASS, DISPOSITION_REJECT, DISPOSITION_REVIEW,
    DISPOSITION_CAPTURE_RETRY, DISPOSITION_MEASUREMENT,
}

# Human final decisions (the only finalization).
FINAL_PASS = "pass"
FINAL_REJECT = "reject"
FINAL_REVIEW = "review"
VALID_FINAL_DECISIONS = {FINAL_PASS, FINAL_REJECT, FINAL_REVIEW}


class ProductionInspectionSession(Base):
    __tablename__ = "qc_production_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    station_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    operator_id: Mapped[Optional[str]] = mapped_column(String(128))
    production_mode: Mapped[str] = mapped_column(String(32), nullable=False, default=PRODUCTION_MODE_ASSISTED)
    # open | closed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    readiness_snapshot_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ProductionCapture(Base):
    __tablename__ = "qc_production_captures"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    session_id: Mapped[str] = mapped_column(
        ForeignKey("qc_production_sessions.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    image_reference: Mapped[str] = mapped_column(String(1024), nullable=False)
    capture_metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ProductionInspectionRun(Base):
    __tablename__ = "qc_production_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    session_id: Mapped[str] = mapped_column(
        ForeignKey("qc_production_sessions.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    prompt_schema_version: Mapped[Optional[str]] = mapped_column(String(64))
    # running | completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    # Recommended overall disposition only (never a final decision).
    overall_disposition: Mapped[Optional[str]] = mapped_column(String(32))
    detection_result_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ProductionDetectionResult(Base):
    __tablename__ = "qc_production_detection_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    run_id: Mapped[str] = mapped_column(
        ForeignKey("qc_production_runs.id"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # Provenance: which confirmed knowledge this result was judged against.
    confirmed_visual_rule_id: Mapped[Optional[str]] = mapped_column(String(64))
    visual_rule_memory_id: Mapped[Optional[str]] = mapped_column(String(64))
    checkpoint_category: Mapped[Optional[str]] = mapped_column(String(48))
    # Recommended disposition (never final).
    disposition: Mapped[str] = mapped_column(String(32), nullable=False, default=DISPOSITION_REVIEW)
    observed_features_json: Mapped[Optional[list]] = mapped_column(JSON)
    defect_features_json: Mapped[Optional[list]] = mapped_column(JSON)
    normal_features_matched_json: Mapped[Optional[list]] = mapped_column(JSON)
    evidence_regions_json: Mapped[Optional[list]] = mapped_column(JSON)
    review_required_conditions_json: Mapped[Optional[list]] = mapped_column(JSON)
    source_image_reference: Mapped[Optional[str]] = mapped_column(String(1024))
    capture_metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    uncertainty: Mapped[Optional[str]] = mapped_column(Text)
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    prompt_schema_version: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class ProductionEvidencePacket(Base):
    """Append-only aggregated evidence packet for a run (audit)."""

    __tablename__ = "qc_production_evidence_packets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    run_id: Mapped[str] = mapped_column(
        ForeignKey("qc_production_runs.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    packet_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class HumanFinalDecision(Base):
    """The ONLY finalization. Append-only audit record with actor + reason."""

    __tablename__ = "qc_production_final_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    run_id: Mapped[str] = mapped_column(
        ForeignKey("qc_production_runs.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # pass | reject | review
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(128), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text)
    recommended_disposition: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
