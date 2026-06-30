"""Human feedback schema + misjudgment taxonomy (PRD §10.7, §18)."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

Verdict = Literal["pass", "fail", "review_required"]


class MisjudgmentType(str, Enum):
    FALSE_PASS = "false_pass"
    FALSE_FAIL = "false_fail"
    WRONG_DEFECT_TYPE = "wrong_defect_type"
    WRONG_REGION = "wrong_region"
    UNCLEAR_EVIDENCE = "unclear_evidence"
    MISSED_INCIDENTAL_FINDING = "missed_incidental_finding"
    OVER_SENSITIVE_TO_CAPTURE_ARTIFACT = "over_sensitive_to_capture_artifact"
    UNDER_SENSITIVE_TO_SUBTLE_DEFECT = "under_sensitive_to_subtle_defect"
    NONE = "none"


class HumanFeedback(BaseModel):
    """Human review of one inspection (PRD §10.7)."""

    feedback_id: str
    inspection_id: str
    reviewer_id: str = ""
    ai_result: Verdict
    human_result: Verdict
    misjudgment_type: MisjudgmentType = MisjudgmentType.NONE
    corrected_checkpoint_results: list[dict] = Field(default_factory=list)
    review_comment: str = ""
    should_add_to_training_pack: bool = False
    tenant_id: Optional[str] = None
    created_at: Optional[datetime] = None

    def is_false_pass(self) -> bool:
        """A false pass is when AI said pass but the human says it should fail."""
        return (
            self.misjudgment_type == MisjudgmentType.FALSE_PASS
            or (self.ai_result == "pass" and self.human_result == "fail")
        )
