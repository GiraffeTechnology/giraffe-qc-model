"""Inspection request/result schemas (PRD §10.5, §10.6)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

Verdict = Literal["pass", "fail", "review_required"]


class InspectionRequest(BaseModel):
    """Request to inspect one captured item (PRD §10.5)."""

    inspection_id: str
    sku_id: str
    station_id: str
    operator_id: str = ""
    training_pack_id: str = ""
    playbook_version: str = ""
    standard_revision_id: str = ""
    image_paths: list[str] = Field(default_factory=list)
    reference_image_paths: list[str] = Field(default_factory=list)
    inspection_context: dict = Field(default_factory=dict)
    requested_detection_points: list[str] = Field(default_factory=list)
    tenant_id: Optional[str] = None
    created_at: Optional[datetime] = None


class CheckpointResult(BaseModel):
    """Per-checkpoint result (PRD §10.6)."""

    code: str
    checkpoint_category: str
    result: Verdict
    visual_evidence: str = ""
    normal_vs_defect_reasoning: str = ""
    pseudo_defect_analysis: str = ""
    confidence: float = 0.0
    severity: str = "major"
    requires_human_review: bool = False
    # Why the finalizer forced a particular checkpoint verdict, if it did.
    finalization_note: str = ""


class IncidentalFinding(BaseModel):
    description: str
    severity: Literal["minor", "major", "critical"] = "minor"
    visual_evidence: str = ""
    requires_human_review: bool = False


class CaptureQuality(BaseModel):
    acceptable: bool = True
    issues: list[str] = Field(default_factory=list)


class InspectionResult(BaseModel):
    """Finalized inspection result (PRD §10.6)."""

    inspection_id: str
    overall_result: Verdict
    model_provider: str = ""
    runtime_profile: str = ""
    model_name: str = ""
    training_pack_id: str = ""
    playbook_version: str = ""
    checkpoint_results: list[CheckpointResult] = Field(default_factory=list)
    incidental_findings: list[IncidentalFinding] = Field(default_factory=list)
    capture_quality: CaptureQuality = Field(default_factory=CaptureQuality)
    finalization_rule_applied: str = ""
    requires_human_review: bool = False
    confidence: float = 0.0
    created_at: Optional[datetime] = None
