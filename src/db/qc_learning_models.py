"""SQLAlchemy models for the Phase 2A QC rule-learning engine (PRD §12).

These tables persist the rule-learning *proposal* workflow: jobs, their inputs,
learned detection-point / visual-rule proposals, supervisor approvals, and the
auditable learning report. Nothing here is active until a supervisor approves
and applies it.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow


class QCLearningJob(Base):
    __tablename__ = "qc_learning_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    station_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # draft | input_ready | running | proposed | reviewing | approved |
    # partially_approved | rejected | applied | failed | cancelled
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    runtime_profile: Mapped[str] = mapped_column(String(32), nullable=False, default="server")
    provider: Mapped[Optional[str]] = mapped_column(String(64))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class QCLearningInput(Base):
    __tablename__ = "qc_learning_inputs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    learning_job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_learning_jobs.id"), nullable=False, index=True
    )
    # operator_requirement | sample_refs
    input_type: Mapped[str] = mapped_column(String(32), nullable=False, default="operator_requirement")
    # operator_text | speech_transcript | email | im | uploaded_standard
    source: Mapped[Optional[str]] = mapped_column(String(32))
    text_content: Mapped[Optional[str]] = mapped_column(Text)
    sample_refs_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class QCLearnedDetectionPointProposal(Base):
    __tablename__ = "qc_learned_detection_point_proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    # Nullable so a proposal can originate from either a learning job (PR 20)
    # or a rule-authoring job over a source fragment (PR 22).
    learning_job_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("qc_learning_jobs.id"), nullable=True, index=True
    )
    # PR 22: authoring-run + source-fragment traceability (both nullable so the
    # PR 20 learning path is unaffected).
    rule_authoring_job_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    source_fragment_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    source_requirement: Mapped[Optional[str]] = mapped_column(Text)
    proposed_code: Mapped[str] = mapped_column(String(64), nullable=False)
    proposed_name: Mapped[Optional[str]] = mapped_column(String(256))
    proposed_checkpoint_category: Mapped[str] = mapped_column(String(48), nullable=False)
    proposed_ai_role: Mapped[str] = mapped_column(String(48), nullable=False)
    target_region: Mapped[Optional[str]] = mapped_column(String(256))
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="major")
    normal_visual_features_json: Mapped[Optional[list]] = mapped_column(JSON)
    defect_visual_features_json: Mapped[Optional[list]] = mapped_column(JSON)
    known_pseudo_defects_json: Mapped[Optional[list]] = mapped_column(JSON)
    decision_rule: Mapped[Optional[str]] = mapped_column(Text)
    review_required_conditions_json: Mapped[Optional[list]] = mapped_column(JSON)
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # PR 22: structured evidence-required list (questions_or_ambiguities uses
    # the existing uncertainties_json column).
    evidence_required_json: Mapped[Optional[list]] = mapped_column(JSON)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    uncertainties_json: Mapped[Optional[list]] = mapped_column(JSON)
    # PR 22 physical-measurement guard override note (supervisor-visible).
    guard_override_note: Mapped[Optional[str]] = mapped_column(Text)
    # proposed | approved | rejected | applied  (+ edited via approval records)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    approved_by: Mapped[Optional[str]] = mapped_column(String(128))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    applied_detection_point_id: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class QCLearnedVisualRuleProposal(Base):
    __tablename__ = "qc_learned_visual_rule_proposals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    learning_job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_learning_jobs.id"), nullable=False, index=True
    )
    detection_point_proposal_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("qc_learned_detection_point_proposals.id"), index=True
    )
    # normal_feature | defect_feature | pseudo_defect | decision_rule | review_required_condition
    rule_type: Mapped[str] = mapped_column(String(48), nullable=False)
    rule_text: Mapped[str] = mapped_column(Text, nullable=False)
    source_samples_json: Mapped[Optional[list]] = mapped_column(JSON)
    source_requirement: Mapped[Optional[str]] = mapped_column(Text)
    provider: Mapped[Optional[str]] = mapped_column(String(64))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    runtime_profile: Mapped[str] = mapped_column(String(32), nullable=False, default="server")
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    approved_by: Mapped[Optional[str]] = mapped_column(String(128))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class QCLearningApproval(Base):
    __tablename__ = "qc_learning_approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    learning_job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_learning_jobs.id"), nullable=False, index=True
    )
    # detection_point | visual_rule
    proposal_type: Mapped[str] = mapped_column(String(32), nullable=False)
    proposal_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # approve | reject | edit
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    edited_payload_json: Mapped[Optional[dict]] = mapped_column(JSON)
    reviewer_id: Mapped[Optional[str]] = mapped_column(String(128))
    review_comment: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class QCLearningReport(Base):
    __tablename__ = "qc_learning_reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    learning_job_id: Mapped[str] = mapped_column(
        ForeignKey("qc_learning_jobs.id"), nullable=False, index=True
    )
    report_json: Mapped[Optional[dict]] = mapped_column(JSON)
    requires_supervisor_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_apply_to_training_pack: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
