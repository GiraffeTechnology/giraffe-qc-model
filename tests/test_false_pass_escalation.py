"""False-pass P0 escalation tests (PRD §18.3, §23.7)."""
from __future__ import annotations

from tests.qcm_factories import make_inspector

from src.qc_model.feedback_escalation import process_human_feedback
from src.qc_model.schemas.digital_inspector import InspectorStatus
from src.qc_model.schemas.feedback import HumanFeedback, MisjudgmentType


def _false_pass_feedback() -> HumanFeedback:
    return HumanFeedback(
        feedback_id="fb1",
        inspection_id="ins1",
        reviewer_id="rev1",
        ai_result="pass",
        human_result="fail",
        misjudgment_type=MisjudgmentType.FALSE_PASS,
        should_add_to_training_pack=True,
    )


def test_false_pass_creates_p0_misjudgment_record():
    inspector = make_inspector(status=InspectorStatus.ACTIVE)
    outcome = process_human_feedback(_false_pass_feedback(), inspector)
    assert outcome.is_p0_incident is True
    assert outcome.misjudgment_case is not None
    assert outcome.misjudgment_case.priority == "P0"
    assert outcome.misjudgment_case.misjudgment_type == "false_pass"


def test_false_pass_suspends_inspector():
    inspector = make_inspector(status=InspectorStatus.ACTIVE)
    outcome = process_human_feedback(_false_pass_feedback(), inspector)
    assert outcome.inspector.status == InspectorStatus.SUSPENDED
    # original object is not mutated
    assert inspector.status == InspectorStatus.ACTIVE


def test_false_pass_downgrades_on_trial_inspector():
    inspector = make_inspector(status=InspectorStatus.ON_TRIAL)
    outcome = process_human_feedback(_false_pass_feedback(), inspector)
    assert outcome.inspector.status == InspectorStatus.SUSPENDED


def test_false_pass_sample_eligible_for_training_pack():
    outcome = process_human_feedback(_false_pass_feedback(), make_inspector())
    assert outcome.misjudgment_case.eligible_for_training_pack is True


def test_requalification_required_before_reactivation():
    outcome = process_human_feedback(_false_pass_feedback(), make_inspector())
    assert outcome.requires_requalification is True
    assert outcome.inspector.requires_requalification is True


def test_implicit_false_pass_detected_from_results():
    # No explicit misjudgment_type, but ai=pass/human=fail is a false pass.
    fb = HumanFeedback(
        feedback_id="fb2",
        inspection_id="ins2",
        ai_result="pass",
        human_result="fail",
        misjudgment_type=MisjudgmentType.NONE,
    )
    outcome = process_human_feedback(fb, make_inspector(status=InspectorStatus.ACTIVE))
    assert outcome.is_p0_incident is True
    assert outcome.inspector.status == InspectorStatus.SUSPENDED


def test_non_false_pass_feedback_does_not_suspend():
    fb = HumanFeedback(
        feedback_id="fb3",
        inspection_id="ins3",
        ai_result="fail",
        human_result="fail",
        misjudgment_type=MisjudgmentType.NONE,
    )
    inspector = make_inspector(status=InspectorStatus.ACTIVE)
    outcome = process_human_feedback(fb, inspector)
    assert outcome.is_p0_incident is False
    assert outcome.inspector.status == InspectorStatus.ACTIVE
