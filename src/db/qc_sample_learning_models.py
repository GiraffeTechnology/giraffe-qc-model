"""SQLAlchemy models for the VLM sample-learning pipeline (PR 23 §2, §3).

Per-sample provenance is preserved: each ``VisualFeatureObservation`` is
traceable to the exact sample image it came from, and each
``SampleEvidenceAnchor`` is an append-only link from an observation to a sample
image (+ region). ``VisualRuleMemory`` is the aggregated, supervisor-approvable
unit. ``QCConfirmedVisualRule`` is the ONLY Training-Pack write target (via the
apply endpoint); it enforces no-silent-overwrite.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow


class SampleGroup(Base):
    __tablename__ = "qc_sample_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64))
    # reference | positive | defect | boundary | capture_artifact
    sample_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # [{ "sample_id": str, "image_reference": str }]
    samples_json: Mapped[Optional[list]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class SampleLearningJob(Base):
    __tablename__ = "qc_sample_learning_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sample_group_id: Mapped[str] = mapped_column(
        ForeignKey("qc_sample_groups.id"), nullable=False, index=True
    )
    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    observation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class VisualFeatureObservation(Base):
    __tablename__ = "qc_visual_feature_observations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    sample_learning_job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_sample_learning_jobs.id"), nullable=False, index=True
    )
    sample_group_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64))
    # Per-sample provenance (never collapsed to aggregate-only).
    source_sample_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    image_reference: Mapped[Optional[str]] = mapped_column(String(1024))
    feature_type: Mapped[str] = mapped_column(String(48), nullable=False)
    evidence_region_json: Mapped[Optional[dict]] = mapped_column(JSON)  # bbox, nullable
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    uncertainty: Mapped[Optional[str]] = mapped_column(Text)
    rule_implication: Mapped[Optional[str]] = mapped_column(Text)
    requires_human_review: Mapped[bool] = mapped_column(default=True, nullable=False)
    # Structured observation lists (§3).
    normal_visual_features_json: Mapped[Optional[list]] = mapped_column(JSON)
    acceptable_variations_json: Mapped[Optional[list]] = mapped_column(JSON)
    defect_visual_features_json: Mapped[Optional[list]] = mapped_column(JSON)
    known_pseudo_defects_json: Mapped[Optional[list]] = mapped_column(JSON)
    capture_artifact_risks_json: Mapped[Optional[list]] = mapped_column(JSON)
    evidence_required_json: Mapped[Optional[list]] = mapped_column(JSON)
    review_required_conditions_json: Mapped[Optional[list]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class SampleEvidenceAnchor(Base):
    """Append-only link from an observation to a specific sample image + region."""

    __tablename__ = "qc_sample_evidence_anchors"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    observation_id: Mapped[str] = mapped_column(
        ForeignKey("qc_visual_feature_observations.id"), nullable=False, index=True
    )
    source_sample_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    image_reference: Mapped[Optional[str]] = mapped_column(String(1024))
    evidence_region_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class VisualRuleMemory(Base):
    __tablename__ = "qc_visual_rule_memory"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    sample_learning_job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_sample_learning_jobs.id"), nullable=False, index=True
    )
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    feature_type: Mapped[str] = mapped_column(String(48), nullable=False)
    normal_visual_features_json: Mapped[Optional[list]] = mapped_column(JSON)
    acceptable_variations_json: Mapped[Optional[list]] = mapped_column(JSON)
    defect_visual_features_json: Mapped[Optional[list]] = mapped_column(JSON)
    known_pseudo_defects_json: Mapped[Optional[list]] = mapped_column(JSON)
    capture_artifact_risks_json: Mapped[Optional[list]] = mapped_column(JSON)
    evidence_required_json: Mapped[Optional[list]] = mapped_column(JSON)
    review_required_conditions_json: Mapped[Optional[list]] = mapped_column(JSON)
    observation_ids_json: Mapped[Optional[list]] = mapped_column(JSON)  # provenance
    # proposed | approved | rejected | applied
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    approved_by: Mapped[Optional[str]] = mapped_column(String(128))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    review_comment: Mapped[Optional[str]] = mapped_column(Text)
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PseudoDefectRule(Base):
    __tablename__ = "qc_pseudo_defect_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    visual_rule_memory_id: Mapped[str] = mapped_column(
        ForeignKey("qc_visual_rule_memory.id"), nullable=False, index=True
    )
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64))
    pattern_text: Mapped[str] = mapped_column(Text, nullable=False)
    # normal | high  (high-risk pseudo-defects must be resolved before readiness)
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    source_sample_id: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class CaptureArtifactRule(Base):
    __tablename__ = "qc_capture_artifact_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    visual_rule_memory_id: Mapped[str] = mapped_column(
        ForeignKey("qc_visual_rule_memory.id"), nullable=False, index=True
    )
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64))
    pattern_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_sample_id: Mapped[Optional[str]] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class QCConfirmedVisualRule(Base):
    """A confirmed visual rule written into a Training Pack by the apply path.

    This is the ONLY Training-Pack write target for sample learning. Conflict
    detection (same training_pack + detection_point + feature_type, different
    confirmed content) prevents silent overwrite.
    """

    __tablename__ = "qc_confirmed_visual_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detection_point_code: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    feature_type: Mapped[str] = mapped_column(String(48), nullable=False)
    content_json: Mapped[Optional[dict]] = mapped_column(JSON)
    source_memory_id: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(128))
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
