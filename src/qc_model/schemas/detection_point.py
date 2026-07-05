"""Detection point schema with proposed + confirmed category workflow.

A detection point is born with a *proposed* checkpoint category (from
deterministic structuring of operator input). It becomes usable for active
production inspection only after a QC supervisor *confirms* (or edits) the
category. Both proposed and confirmed data are preserved (PRD §7).
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from src.qc_model.schemas.checkpoint import (
    ai_can_be_primary_judge,
    default_ai_role,
    is_supported_category,
)


class DetectionPoint(BaseModel):
    """One structured detection point (PRD §10.3)."""

    code: str
    name: str = ""
    raw_operator_requirement: str = ""

    # Category confirmation workflow (PRD §7.2).
    proposed_checkpoint_category: str
    confirmed_checkpoint_category: Optional[str] = None
    category_confirmed_by: Optional[str] = None
    category_confirmed_at: Optional[datetime] = None
    classification_rationale: str = ""

    severity: str = "major"  # "minor" | "major" | "critical"
    target_region: str = ""

    normal_visual_features: list[str] = Field(default_factory=list)
    defect_visual_features: list[str] = Field(default_factory=list)
    known_pseudo_defects: list[str] = Field(default_factory=list)
    decision_rule: str = ""
    review_required_conditions: list[str] = Field(default_factory=list)
    evidence_required: bool = True

    # ── Derived helpers ───────────────────────────────────────────────────

    @property
    def effective_category(self) -> Optional[str]:
        """The confirmed category if present, else None (proposed is not active)."""
        return self.confirmed_checkpoint_category

    @property
    def ai_role(self) -> str:
        """AI role derived from the *effective* (confirmed) category.

        Until confirmed, role is record_only (cannot be AI-primary).
        """
        return default_ai_role(self.effective_category).value

    def is_category_confirmed(self) -> bool:
        """True only when a supported category was confirmed by a supervisor."""
        return (
            self.confirmed_checkpoint_category is not None
            and is_supported_category(self.confirmed_checkpoint_category)
            and self.category_confirmed_by is not None
        )

    def is_usable_for_active_inspection(self) -> bool:
        """A detection point may drive active inspection only once confirmed."""
        return self.is_category_confirmed()

    def ai_can_be_primary_judge(self) -> bool:
        """AI-primary only for a *confirmed* visual_defect checkpoint."""
        if not self.is_category_confirmed():
            return False
        return ai_can_be_primary_judge(self.confirmed_checkpoint_category)

    def confirm_category(
        self,
        category: str,
        confirmed_by: str,
        confirmed_at: datetime,
        rationale: str = "",
    ) -> "DetectionPoint":
        """Return a copy with the confirmed category set."""
        return self.model_copy(
            update={
                "confirmed_checkpoint_category": category,
                "category_confirmed_by": confirmed_by,
                "category_confirmed_at": confirmed_at,
                "classification_rationale": rationale or self.classification_rationale,
            }
        )
