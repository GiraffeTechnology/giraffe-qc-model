"""Physical-measurement boundary during learning (PRD §8, §18.3)."""
from __future__ import annotations

import pytest

from src.qc_model.learning.requirement_structuring import structure_requirement
from src.qc_model.schemas.checkpoint import ai_can_be_primary_judge


@pytest.mark.parametrize(
    "requirement",
    [
        "Verify the chain link count",
        "Measure the total length",
        "Check the hole diameter",
        "Confirm the chemical composition",
        "Record the weight",
        "Measure the angle between arms",
    ],
)
def test_physical_measurement_requirements_are_not_ai_primary(requirement):
    item = structure_requirement(requirement)
    assert item["proposed_checkpoint_category"] == "physical_measurement"
    assert item["proposed_ai_role"] == "record_only"
    assert not ai_can_be_primary_judge(item["proposed_checkpoint_category"])


def test_physical_measurement_decision_rule_and_review_conditions():
    item = structure_requirement("Verify chain link count")
    assert "operator" in item["decision_rule"].lower()
    assert "measurement evidence missing" in item["review_required_conditions"]
    assert "fixture photo missing" in item["review_required_conditions"]


def test_visual_defect_can_be_ai_primary():
    item = structure_requirement("Check petal cracks")
    assert item["proposed_checkpoint_category"] == "visual_defect"
    assert item["proposed_ai_role"] == "primary_visual_judge"
    assert ai_can_be_primary_judge(item["proposed_checkpoint_category"])


def test_validator_normalizes_over_permissive_physical_role():
    from src.qc_model.learning.schemas import (
        LearnedDetectionPointProposal,
        QCRuleLearningResponse,
    )
    from src.qc_model.learning.validator import validate_response

    # A misbehaving provider tries to make a physical measurement AI-primary.
    bad = LearnedDetectionPointProposal(
        proposal_id="p1",
        learning_job_id="j1",
        proposed_code="chain_link_count",
        proposed_checkpoint_category="physical_measurement",
        proposed_ai_role="primary_visual_judge",
    )
    result = validate_response(
        QCRuleLearningResponse(provider="x", model="y", detection_point_proposals=[bad])
    )
    assert result.valid is True
    # Role is normalized down to record_only.
    assert result.normalized.detection_point_proposals[0].proposed_ai_role == "record_only"
