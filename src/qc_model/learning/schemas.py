"""Pydantic schemas + enums for the Phase 2A rule-learning engine (PRD §7, §11).

These are vendor-neutral: a learning provider consumes a
``QCRuleLearningRequest`` and returns a ``QCRuleLearningResponse`` full of
*proposals*. Nothing here is authoritative — every proposal carries
``requires_supervisor_confirmation = True`` and starts in ``proposed`` status.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class LearningJobStatus(str, Enum):
    DRAFT = "draft"
    INPUT_READY = "input_ready"
    RUNNING = "running"
    PROPOSED = "proposed"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    PARTIALLY_APPROVED = "partially_approved"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    APPLIED = "applied"


class RuleType(str, Enum):
    NORMAL_FEATURE = "normal_feature"
    DEFECT_FEATURE = "defect_feature"
    PSEUDO_DEFECT = "pseudo_defect"
    DECISION_RULE = "decision_rule"
    REVIEW_REQUIRED_CONDITION = "review_required_condition"


# ── Provider request / response (vendor-neutral) ──────────────────────────


class LearningSampleRefs(BaseModel):
    """Sample references grouped by category (PRD §6.3)."""

    reference_images: list[str] = Field(default_factory=list)
    positive_samples: list[str] = Field(default_factory=list)
    defect_samples: list[str] = Field(default_factory=list)
    boundary_samples: list[str] = Field(default_factory=list)
    capture_artifact_samples: list[str] = Field(default_factory=list)


class QCRuleLearningRequest(BaseModel):
    """Provider-neutral rule-learning request (PRD §9)."""

    learning_job_id: str
    training_pack_id: str
    sku_id: str
    station_id: str
    runtime_profile: str = "server"
    operator_requirements: list[str] = Field(default_factory=list)
    sample_refs: LearningSampleRefs = Field(default_factory=LearningSampleRefs)
    existing_detection_point_codes: list[str] = Field(default_factory=list)
    capture_protocol: dict = Field(default_factory=dict)


class LearnedDetectionPointProposal(BaseModel):
    """Learned detection point proposal (PRD §7.1)."""

    proposal_id: str
    learning_job_id: str
    source_requirement: str = ""
    proposed_code: str
    proposed_name: str = ""
    proposed_checkpoint_category: str
    proposed_ai_role: str
    target_region: str = ""
    severity: str = "major"
    normal_visual_features: list[str] = Field(default_factory=list)
    defect_visual_features: list[str] = Field(default_factory=list)
    known_pseudo_defects: list[str] = Field(default_factory=list)
    decision_rule: str = ""
    review_required_conditions: list[str] = Field(default_factory=list)
    evidence_required: bool = True
    confidence: float = 0.0
    uncertainties: list[str] = Field(default_factory=list)
    requires_supervisor_confirmation: bool = True
    status: ProposalStatus = ProposalStatus.PROPOSED


class LearnedVisualRuleProposal(BaseModel):
    """Learned visual rule proposal (PRD §7.2)."""

    rule_id: str
    learning_job_id: str
    detection_point_proposal_id: str
    rule_type: RuleType
    rule_text: str
    source_samples: list[str] = Field(default_factory=list)
    source_requirement: str = ""
    provider: str = ""
    model: str = ""
    runtime_profile: str = "server"
    confidence: float = 0.0
    requires_supervisor_confirmation: bool = True
    status: ProposalStatus = ProposalStatus.PROPOSED


class QCRuleLearningResponse(BaseModel):
    """Provider-neutral response. ``valid=False`` fails the learning job closed."""

    provider: str
    model: str
    runtime_profile: str = "server"
    detection_point_proposals: list[LearnedDetectionPointProposal] = Field(default_factory=list)
    visual_rule_proposals: list[LearnedVisualRuleProposal] = Field(default_factory=list)
    physical_measurement_warnings: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    valid: bool = True
    error: Optional[str] = None


class LearningReport(BaseModel):
    """Auditable learning report (PRD §7.3)."""

    learning_job_id: str
    training_pack_id: str
    sku_id: str
    station_id: str
    provider: str
    model: str
    runtime_profile: str = "server"
    input_summary: dict = Field(default_factory=dict)
    detection_point_proposals: list[dict] = Field(default_factory=list)
    visual_rule_proposals: list[dict] = Field(default_factory=list)
    physical_measurement_warnings: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    requires_supervisor_review: bool = True
    can_apply_to_training_pack: bool = False
    created_at: Optional[datetime] = None
