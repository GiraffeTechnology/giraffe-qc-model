"""Physical measurement boundary tests (PRD §5, §23.3)."""
from __future__ import annotations

import pytest

from tests.qcm_factories import make_detection_point

from src.qc_model.boundary import (
    PhysicalMeasurementBoundaryError,
    assert_ai_not_primary,
    suggest_category,
)
from src.qc_model.finalizer import finalize
from src.qc_model.providers.base import (
    ProviderCheckpointResult,
    VisualInspectionResponse,
)
from src.qc_model.schemas.checkpoint import (
    CheckpointCategory,
    ai_can_be_primary_judge,
    is_supported_category,
)
from src.qc_model.schemas.inspection import CaptureQuality


def _finalize_one(dp, raw_result="pass"):
    response = VisualInspectionResponse(
        overall_result="pass",
        checkpoint_results=[
            ProviderCheckpointResult(code=dp.code, result=raw_result, visual_evidence="seen")
        ],
        provider="mock_vlm",
        model="mock-vlm-v1",
        valid=True,
    )
    return finalize(
        inspection_id="ins1",
        response=response,
        detection_points=[dp],
        capture_quality=CaptureQuality(acceptable=True),
    )


def test_physical_measurement_cannot_use_ai_as_primary_judge():
    assert not ai_can_be_primary_judge(CheckpointCategory.PHYSICAL_MEASUREMENT.value)
    dp = make_detection_point(category="physical_measurement", severity="major")
    # Even if the model says pass, AI is not the primary judge → review_required.
    result = _finalize_one(dp, raw_result="pass")
    assert result.overall_result == "review_required"
    assert result.checkpoint_results[0].finalization_note == "ai_not_primary_judge_for_physical_measurement"


def test_chain_link_count_classified_as_physical_measurement():
    assert suggest_category("Verify the chain link count equals 24") == "physical_measurement"
    assert suggest_category("measure hole diameter and length") == "physical_measurement"


def test_visual_defect_can_use_ai_as_primary_judge():
    assert ai_can_be_primary_judge(CheckpointCategory.VISUAL_DEFECT.value)
    dp = make_detection_point(category="visual_defect", severity="critical")
    result = _finalize_one(dp, raw_result="pass")
    assert result.overall_result == "pass"


def test_unsupported_category_returns_review_required():
    assert not is_supported_category("made_up_category")
    dp = make_detection_point(category="visual_defect")
    # Force an unsupported confirmed category.
    dp = dp.model_copy(update={"confirmed_checkpoint_category": "made_up_category"})
    result = _finalize_one(dp)
    assert result.overall_result == "review_required"
    assert result.checkpoint_results[0].finalization_note == "checkpoint_category_unsupported"


def test_unconfirmed_category_returns_review_required():
    dp = make_detection_point(confirmed=False)
    result = _finalize_one(dp)
    assert result.overall_result == "review_required"
    assert result.checkpoint_results[0].finalization_note == "checkpoint_category_unconfirmed"


def test_assert_ai_not_primary_raises_for_non_visual():
    with pytest.raises(PhysicalMeasurementBoundaryError):
        assert_ai_not_primary("physical_measurement")
    # Does not raise for visual_defect.
    assert_ai_not_primary("visual_defect")


def test_rule_verification_and_subjective_are_not_ai_primary():
    assert not ai_can_be_primary_judge("rule_verification")
    assert not ai_can_be_primary_judge("subjective_judgment")
