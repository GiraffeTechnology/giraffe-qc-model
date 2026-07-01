"""Digital inspector lifecycle tests (PRD §11, §23.5)."""
from __future__ import annotations

from tests.qcm_factories import make_inspector, make_request, make_training_pack

from src.qc_model.lifecycle import (
    apply_lifecycle_policy,
    can_inspect,
    can_transition,
    requires_mandatory_human_review,
)
from src.qc_model.providers.mock_provider import MockVLMProvider
from src.qc_model.runner import run_inspection
from src.qc_model.schemas.digital_inspector import InspectorStatus


def _run(status, scripted=None):
    pack = make_training_pack()
    inspector = make_inspector(status=status)
    return run_inspection(
        make_request(),
        pack,
        inspector,
        provider=MockVLMProvider(scripted=scripted or {"missing_rhinestone": "pass"}),
    )


def test_draft_inspector_cannot_inspect():
    assert not can_inspect(InspectorStatus.DRAFT)
    result = _run(InspectorStatus.DRAFT)
    assert result.overall_result == "review_required"
    assert "draft" in result.finalization_rule_applied


def test_learning_inspector_cannot_inspect_production():
    assert not can_inspect(InspectorStatus.LEARNING)
    result = _run(InspectorStatus.LEARNING)
    assert result.overall_result == "review_required"


def test_exam_failed_inspector_cannot_inspect():
    assert not can_inspect(InspectorStatus.EXAM_FAILED)
    result = _run(InspectorStatus.EXAM_FAILED)
    assert result.overall_result == "review_required"


def test_on_trial_inspector_requires_human_review():
    assert requires_mandatory_human_review(InspectorStatus.ON_TRIAL)
    result = _run(InspectorStatus.ON_TRIAL, scripted={"missing_rhinestone": "pass"})
    assert result.requires_human_review is True
    assert all(cp.requires_human_review for cp in result.checkpoint_results)
    assert "on_trial_mandatory_human_review" in result.finalization_rule_applied


def test_active_inspector_can_inspect():
    assert can_inspect(InspectorStatus.ACTIVE)
    result = _run(InspectorStatus.ACTIVE, scripted={"missing_rhinestone": "pass"})
    assert result.overall_result == "pass"


def test_suspended_inspector_only_returns_review_required():
    # Even if the model would say fail, suspended emits review_required only.
    result = _run(InspectorStatus.SUSPENDED, scripted={"missing_rhinestone": "fail"})
    assert result.overall_result == "review_required"
    assert "inspector_suspended_review_required_only" in result.finalization_rule_applied


def test_lifecycle_transition_rules():
    assert can_transition(InspectorStatus.EXAM_PASSED, InspectorStatus.ON_TRIAL)
    assert can_transition(InspectorStatus.ON_TRIAL, InspectorStatus.ACTIVE)
    assert can_transition(InspectorStatus.ACTIVE, InspectorStatus.SUSPENDED)
    # Cannot jump straight from draft to active.
    assert not can_transition(InspectorStatus.DRAFT, InspectorStatus.ACTIVE)
    # Retired is terminal.
    assert not can_transition(InspectorStatus.RETIRED, InspectorStatus.ACTIVE)
