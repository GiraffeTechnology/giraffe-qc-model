"""Deterministic finalization tests (PRD §14.4, §23.6)."""
from __future__ import annotations

from tests.qcm_factories import make_detection_point

from src.qc_model.finalizer import finalize
from src.qc_model.providers.base import (
    ProviderCaptureQuality,
    ProviderCheckpointResult,
    ProviderIncidentalFinding,
    VisualInspectionResponse,
)
from src.qc_model.schemas.inspection import CaptureQuality


def _response(results, valid=True, capture_ok=True, incidental=None, overall="pass"):
    return VisualInspectionResponse(
        overall_result=overall,
        checkpoint_results=results,
        provider="mock_vlm",
        model="mock-vlm-v1",
        valid=valid,
        capture_quality=ProviderCaptureQuality(acceptable=capture_ok),
        incidental_findings=incidental or [],
    )


def _cp(code, result, evidence="seen at region"):
    return ProviderCheckpointResult(code=code, result=result, visual_evidence=evidence)


def _finalize(response, points, capture=None):
    return finalize(
        inspection_id="ins1",
        response=response,
        detection_points=points,
        capture_quality=capture or CaptureQuality(acceptable=True),
    )


def test_model_pass_cannot_override_checkpoint_fail():
    dp = make_detection_point(code="missing_rhinestone", severity="critical")
    # Model claims overall pass, but the checkpoint itself is fail.
    response = _response([_cp("missing_rhinestone", "fail")], overall="pass")
    result = _finalize(response, [dp])
    assert result.overall_result == "fail"
    assert result.finalization_rule_applied == "critical_checkpoint_fail"


def test_invalid_json_returns_review_required():
    dp = make_detection_point()
    response = _response([], valid=False, overall="pass")
    result = _finalize(response, [dp])
    assert result.overall_result == "review_required"
    assert result.finalization_rule_applied == "invalid_model_output"


def test_missing_visual_evidence_returns_review_required():
    dp = make_detection_point(evidence_required=True)
    response = _response([_cp("missing_rhinestone", "pass", evidence="")])
    result = _finalize(response, [dp])
    assert result.overall_result == "review_required"
    assert result.checkpoint_results[0].finalization_note == "evidence_required_but_missing"


def test_capture_quality_failure_returns_review_required():
    dp = make_detection_point(severity="major")
    response = _response([_cp("missing_rhinestone", "pass")], capture_ok=False)
    result = _finalize(
        response, [dp], capture=CaptureQuality(acceptable=False, issues=["blur"])
    )
    assert result.overall_result == "review_required"
    assert result.finalization_rule_applied == "capture_quality_unacceptable"


def test_critical_fail_makes_overall_fail():
    dp = make_detection_point(severity="critical")
    response = _response([_cp("missing_rhinestone", "fail")])
    result = _finalize(response, [dp])
    assert result.overall_result == "fail"


def test_review_required_unless_critical_fail():
    a = make_detection_point(code="a", severity="major")
    b = make_detection_point(code="b", severity="major")
    # One review_required, one pass, no critical fail → overall review_required.
    response = _response([_cp("a", "review_required"), _cp("b", "pass")])
    result = _finalize(response, [a, b])
    assert result.overall_result == "review_required"

    # Add a critical fail → critical fail wins over review_required.
    c = make_detection_point(code="c", severity="critical")
    response2 = _response(
        [_cp("a", "review_required"), _cp("b", "pass"), _cp("c", "fail")]
    )
    result2 = _finalize(response2, [a, b, c])
    assert result2.overall_result == "fail"


def test_all_pass_returns_pass():
    a = make_detection_point(code="a", severity="major")
    b = make_detection_point(code="b", severity="critical")
    response = _response([_cp("a", "pass"), _cp("b", "pass")])
    result = _finalize(response, [a, b])
    assert result.overall_result == "pass"
    assert result.finalization_rule_applied == "all_checkpoints_pass"


def test_unconfirmed_category_checkpoint_forces_review_required():
    dp = make_detection_point(confirmed=False)
    response = _response([_cp("missing_rhinestone", "pass")])
    result = _finalize(response, [dp])
    assert result.overall_result == "review_required"
    assert result.checkpoint_results[0].finalization_note == "checkpoint_category_unconfirmed"


def test_missing_checkpoint_in_model_output_forces_review_required():
    dp = make_detection_point(code="missing_rhinestone")
    # Model returns a result for a different code only.
    response = _response([_cp("other_code", "pass")])
    result = _finalize(response, [dp])
    assert result.overall_result == "review_required"
    assert result.checkpoint_results[0].finalization_note == "checkpoint_result_not_provided"


def test_incidental_critical_finding_forces_review_required():
    dp = make_detection_point(code="a", severity="major")
    response = _response(
        [_cp("a", "pass")],
        incidental=[ProviderIncidentalFinding(description="foreign object", severity="critical")],
    )
    result = _finalize(response, [dp])
    assert result.overall_result == "review_required"
    assert result.finalization_rule_applied == "incidental_critical_finding"


def test_empty_detection_points_returns_review_required():
    response = _response([])
    result = _finalize(response, [])
    assert result.overall_result == "review_required"
    assert result.finalization_rule_applied == "no_detection_points"
