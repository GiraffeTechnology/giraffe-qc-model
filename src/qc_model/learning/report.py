"""Learning report builder (PRD §7.3, §18.5)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.qc_model.learning.schemas import (
    LearningReport,
    QCRuleLearningRequest,
    QCRuleLearningResponse,
)


def build_report(
    request: QCRuleLearningRequest,
    response: QCRuleLearningResponse,
) -> LearningReport:
    """Build an auditable learning report from a validated response.

    ``can_apply_to_training_pack`` is always False here: proposals require
    supervisor approval before anything can be applied.
    """
    input_summary = {
        "operator_requirement_count": len(request.operator_requirements),
        "reference_images": len(request.sample_refs.reference_images),
        "positive_samples": len(request.sample_refs.positive_samples),
        "defect_samples": len(request.sample_refs.defect_samples),
        "boundary_samples": len(request.sample_refs.boundary_samples),
        "capture_artifact_samples": len(request.sample_refs.capture_artifact_samples),
        "existing_detection_point_codes": list(request.existing_detection_point_codes),
    }

    return LearningReport(
        learning_job_id=request.learning_job_id,
        training_pack_id=request.training_pack_id,
        sku_id=request.sku_id,
        station_id=request.station_id,
        provider=response.provider,
        model=response.model,
        runtime_profile=response.runtime_profile,
        input_summary=input_summary,
        detection_point_proposals=[p.model_dump(mode="json") for p in response.detection_point_proposals],
        visual_rule_proposals=[r.model_dump(mode="json") for r in response.visual_rule_proposals],
        physical_measurement_warnings=list(response.physical_measurement_warnings),
        open_questions=list(response.open_questions),
        uncertainties=list(response.uncertainties),
        requires_supervisor_review=True,
        can_apply_to_training_pack=False,
        created_at=datetime.now(timezone.utc),
    )
