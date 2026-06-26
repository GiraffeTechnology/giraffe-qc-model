"""Pad-facing QC model adapter layer.

PR15 keeps the Pad E2E flow runnable without depending on cloud Qwen or Android
MNN inference.  The deterministic adapter converts the job's active checkpoint
snapshot into a model-output shaped payload, then the existing inspection
service owns persistence and final-verdict logic.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.execution_models import QCInspectionMedia
from src.inspection.service import get_active_detection_points_for_job


@dataclass(frozen=True)
class QCModelAdapterResult:
    provider: str
    model_name: str
    raw_output: Dict[str, Any]
    elapsed_ms: int = 0


class DeterministicPadQCAdapter:
    """Deterministic, auditable adapter for Pad E2E acceptance.

    It deliberately does not decide final verdicts.  It only returns one
    checkpoint observation per active detection point, shaped exactly like the
    real model-output ingestion API expects.  Final verdicts remain in
    src.inspection.service.finalize_job().
    """

    provider = "pad-deterministic"
    model_name = "pad-qc-e2e-v1"

    def run(
        self,
        db: Session,
        job_id: str,
        media: Optional[QCInspectionMedia] = None,
        options: Optional[Dict[str, Any]] = None,
    ) -> QCModelAdapterResult:
        opts = options or {}
        force_fail_point_code = opts.get("force_fail_point_code")
        force_low_confidence_point_code = opts.get("force_low_confidence_point_code")
        forced_findings: List[Dict[str, Any]] = list(opts.get("incidental_findings") or [])

        checkpoint_results: List[Dict[str, Any]] = []
        for point in get_active_detection_points_for_job(db, job_id):
            result = "pass"
            confidence = 0.95
            notes = "Deterministic Pad E2E adapter observed checkpoint as pass."
            if force_fail_point_code == point.point_code:
                result = "fail"
                confidence = 0.93
                notes = "Forced fail for Pad E2E adapter validation."
            elif force_low_confidence_point_code == point.point_code:
                result = "low_confidence"
                confidence = 0.35
                notes = "Forced low confidence for Pad E2E adapter validation."

            checkpoint_results.append({
                "point_code": point.point_code,
                "result": result,
                "observed_value": point.expected_value,
                "confidence": confidence,
                "notes": notes,
            })

        raw_output: Dict[str, Any] = {
            "adapter": self.model_name,
            "media_id": media.id if media else None,
            "checkpoint_results": checkpoint_results,
            "incidental_findings": forced_findings,
        }
        return QCModelAdapterResult(
            provider=self.provider,
            model_name=self.model_name,
            raw_output=raw_output,
            elapsed_ms=0,
        )
