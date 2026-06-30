"""Human feedback loop + visual signal interpretation mock tests (PRD §18, §23.8)."""
from __future__ import annotations

import pytest

from tests.qcm_factories import (
    make_detection_point,
    make_inspector,
    make_request,
    make_training_pack,
)

from src.qc_model.providers.mock_provider import MockVLMProvider
from src.qc_model.runner import run_inspection
from src.qc_model.schemas.feedback import HumanFeedback, MisjudgmentType


def test_human_feedback_captures_required_fields():
    fb = HumanFeedback(
        feedback_id="fb1",
        inspection_id="ins1",
        reviewer_id="rev1",
        ai_result="pass",
        human_result="fail",
        misjudgment_type=MisjudgmentType.FALSE_PASS,
        corrected_checkpoint_results=[{"code": "missing_rhinestone", "result": "fail"}],
        review_comment="rhinestone clearly missing",
        should_add_to_training_pack=True,
    )
    assert fb.ai_result == "pass"
    assert fb.human_result == "fail"
    assert fb.misjudgment_type == MisjudgmentType.FALSE_PASS
    assert fb.should_add_to_training_pack is True
    assert fb.is_false_pass() is True


def test_all_misjudgment_types_available():
    expected = {
        "false_pass",
        "false_fail",
        "wrong_defect_type",
        "wrong_region",
        "unclear_evidence",
        "missed_incidental_finding",
        "over_sensitive_to_capture_artifact",
        "under_sensitive_to_subtle_defect",
        "none",
    }
    assert {m.value for m in MisjudgmentType} == expected


# ── Visual signal interpretation mock tests (PRD §23.8) ────────────────────
# These test parser + finalizer behaviour only — NOT real model accuracy.


@pytest.mark.parametrize(
    "scenario,scripted,expected",
    [
        ("normal_reflection_is_pass", {"missing_rhinestone": "pass"}, "pass"),
        ("missing_component_is_fail", {"missing_rhinestone": "fail"}, "fail"),
        ("ambiguous_reflection_is_review", {"missing_rhinestone": "review_required"}, "review_required"),
    ],
)
def test_visual_signal_interpretation_paths(scenario, scripted, expected):
    pack = make_training_pack(detection_points=[make_detection_point(severity="critical")])
    inspector = make_inspector()
    provider = MockVLMProvider(scripted=scripted)
    result = run_inspection(make_request(), pack, inspector, provider=provider)
    assert result.overall_result == expected, scenario


def test_full_loop_inspection_then_false_pass_feedback_suspends():
    """End-to-end: run an (incorrect) pass, then human false-pass feedback."""
    from src.qc_model.feedback_escalation import process_human_feedback
    from src.qc_model.schemas.digital_inspector import InspectorStatus

    pack = make_training_pack(detection_points=[make_detection_point(severity="critical")])
    inspector = make_inspector(status=InspectorStatus.ACTIVE)
    # Model wrongly passes a real defect.
    result = run_inspection(
        make_request(), pack, inspector,
        provider=MockVLMProvider(scripted={"missing_rhinestone": "pass"}),
    )
    assert result.overall_result == "pass"

    fb = HumanFeedback(
        feedback_id="fb1",
        inspection_id=result.inspection_id,
        ai_result=result.overall_result,
        human_result="fail",
        misjudgment_type=MisjudgmentType.FALSE_PASS,
        should_add_to_training_pack=True,
    )
    outcome = process_human_feedback(fb, inspector)
    assert outcome.inspector.status == InspectorStatus.SUSPENDED
    assert outcome.requires_requalification is True
