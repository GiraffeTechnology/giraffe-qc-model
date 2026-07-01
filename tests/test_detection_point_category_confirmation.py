"""Detection point category confirmation tests (PRD §7, §23.3)."""
from __future__ import annotations

from datetime import datetime, timezone

from src.qc_model.schemas.detection_point import DetectionPoint


def _dp(category="visual_defect") -> DetectionPoint:
    return DetectionPoint(code="dp1", proposed_checkpoint_category=category)


def test_proposed_category_alone_is_not_usable():
    dp = _dp()
    assert dp.proposed_checkpoint_category == "visual_defect"
    assert dp.confirmed_checkpoint_category is None
    assert not dp.is_category_confirmed()
    assert not dp.is_usable_for_active_inspection()


def test_confirmation_preserves_both_proposed_and_confirmed():
    dp = _dp("visual_defect")
    confirmed = dp.confirm_category(
        "physical_measurement", "sup1", datetime.now(timezone.utc), "actually a measurement"
    )
    # proposed is preserved, confirmed reflects the supervisor edit
    assert confirmed.proposed_checkpoint_category == "visual_defect"
    assert confirmed.confirmed_checkpoint_category == "physical_measurement"
    assert confirmed.category_confirmed_by == "sup1"
    assert confirmed.category_confirmed_at is not None
    assert confirmed.classification_rationale == "actually a measurement"


def test_confirmed_visual_defect_is_usable_and_ai_primary():
    dp = _dp("visual_defect").confirm_category(
        "visual_defect", "sup1", datetime.now(timezone.utc)
    )
    assert dp.is_usable_for_active_inspection()
    assert dp.ai_can_be_primary_judge()


def test_confirmed_but_unsupported_category_is_not_confirmed():
    dp = _dp("visual_defect").confirm_category(
        "totally_made_up", "sup1", datetime.now(timezone.utc)
    )
    assert not dp.is_category_confirmed()
    assert not dp.is_usable_for_active_inspection()


def test_confirmation_without_supervisor_is_not_confirmed():
    dp = _dp("visual_defect").model_copy(
        update={"confirmed_checkpoint_category": "visual_defect", "category_confirmed_by": None}
    )
    assert not dp.is_category_confirmed()


def test_ai_role_derives_from_confirmed_category():
    physical = _dp("physical_measurement").confirm_category(
        "physical_measurement", "sup1", datetime.now(timezone.utc)
    )
    assert physical.ai_role == "record_only"
    assert not physical.ai_can_be_primary_judge()
