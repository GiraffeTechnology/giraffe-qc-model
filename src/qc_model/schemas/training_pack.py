"""Training Pack, Playbook, and Capture Protocol schemas (PRD §10.2, §12, §16).

A Training Pack binds one SKU + one station to a confirmed Playbook,
reference/sample images, and confirmed detection points. A production
inspector cannot go active without a confirmed Training Pack.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.qc_model.schemas.detection_point import DetectionPoint


class TrainingPackStatus(str, Enum):
    DRAFT = "draft"
    PENDING_OPERATOR_CONFIRMATION = "pending_operator_confirmation"
    TRAINING = "training"
    EXAM_READY = "exam_ready"
    QUALIFIED = "qualified"
    RETIRED = "retired"


class CaptureProtocol(BaseModel):
    """Capture requirements for a Training Pack (PRD §16)."""

    lighting: str = ""
    background: str = ""
    camera_distance: str = ""
    angle: str = ""
    focus: str = ""
    exposure: str = ""
    minimum_resolution: str = ""
    required_views: list[str] = Field(default_factory=list)

    def is_defined(self) -> bool:
        """A capture protocol is 'known' when at least one field is set."""
        return any(
            [
                self.lighting,
                self.background,
                self.camera_distance,
                self.angle,
                self.focus,
                self.exposure,
                self.minimum_resolution,
                self.required_views,
            ]
        )


class Playbook(BaseModel):
    """QC Playbook + structured model comprehension (PRD §12.1)."""

    version: str = "1"
    target_regions: list[str] = Field(default_factory=list)
    fail_conditions: list[str] = Field(default_factory=list)
    review_required_conditions: list[str] = Field(default_factory=list)
    pseudo_defects: list[str] = Field(default_factory=list)
    # Comprehension output; if questions_or_ambiguities is non-empty the
    # Training Pack cannot move to exam_ready.
    questions_or_ambiguities: list[str] = Field(default_factory=list)

    def has_open_questions(self) -> bool:
        return len(self.questions_or_ambiguities) > 0


class TrainingPack(BaseModel):
    """Training Pack (PRD §10.2)."""

    training_pack_id: str
    sku_id: str
    station_id: str
    version: str = "1"
    status: TrainingPackStatus = TrainingPackStatus.DRAFT
    tenant_id: Optional[str] = None

    capture_protocol: CaptureProtocol = Field(default_factory=CaptureProtocol)
    playbook: Optional[Playbook] = None

    reference_images: list[str] = Field(default_factory=list)
    positive_samples: list[str] = Field(default_factory=list)
    defect_samples: list[str] = Field(default_factory=list)
    boundary_samples: list[str] = Field(default_factory=list)
    capture_artifact_samples: list[str] = Field(default_factory=list)

    detection_points: list[DetectionPoint] = Field(default_factory=list)
    qualification_exam: dict = Field(default_factory=dict)

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None

    # ── Validation helpers ────────────────────────────────────────────────

    def missing_requirements(self) -> list[str]:
        """Return the list of unmet structural requirements (PRD §23.4)."""
        problems: list[str] = []
        if self.playbook is None:
            problems.append("missing_playbook")
        if not self.detection_points:
            problems.append("missing_detection_points")
        if not self.reference_images:
            problems.append("missing_reference_image")
        unconfirmed = [
            dp.code for dp in self.detection_points if not dp.is_category_confirmed()
        ]
        if unconfirmed:
            problems.append("unconfirmed_detection_point_categories")
        return problems

    def is_structurally_complete(self) -> bool:
        return not self.missing_requirements()

    def is_confirmed(self) -> bool:
        """A Training Pack is usable for active inspection only when it is
        structurally complete AND in a confirmed/qualified status."""
        return self.is_structurally_complete() and self.status in (
            TrainingPackStatus.QUALIFIED,
            TrainingPackStatus.EXAM_READY,
        )

    def confirmed_detection_points(self) -> list[DetectionPoint]:
        return [dp for dp in self.detection_points if dp.is_category_confirmed()]
