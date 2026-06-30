"""Capture quality gate tests (PRD §16, §23)."""
from __future__ import annotations

from tests.qcm_factories import make_detection_point, make_inspector, make_request, make_training_pack

from src.qc_model.capture_quality import evaluate_capture_quality
from src.qc_model.providers.base import ProviderCaptureQuality
from src.qc_model.providers.mock_provider import MockVLMProvider
from src.qc_model.runner import run_inspection


def test_acceptable_when_no_issues():
    cq = evaluate_capture_quality(ProviderCaptureQuality(acceptable=True, issues=[]))
    assert cq.acceptable is True


def test_unacceptable_when_provider_says_so():
    cq = evaluate_capture_quality(ProviderCaptureQuality(acceptable=False, issues=["blur"]))
    assert cq.acceptable is False
    assert "blur" in cq.issues


def test_fail_closed_when_issues_present_even_if_acceptable_true():
    # Provider contradicts itself (acceptable but with issues) → fail closed.
    cq = evaluate_capture_quality(ProviderCaptureQuality(acceptable=True, issues=["overexposure"]))
    assert cq.acceptable is False


def test_bad_capture_makes_inspection_review_required():
    pack = make_training_pack(detection_points=[make_detection_point(severity="major")])
    inspector = make_inspector()
    provider = MockVLMProvider(
        scripted={"missing_rhinestone": "pass"},
        capture_acceptable=False,
        capture_issues=["target_region_not_visible"],
    )
    result = run_inspection(make_request(), pack, inspector, provider=provider)
    assert result.overall_result == "review_required"
    assert result.finalization_rule_applied == "capture_quality_unacceptable"


def test_bad_capture_does_not_override_critical_fail():
    # A real critical defect should still fail even with bad capture.
    pack = make_training_pack(detection_points=[make_detection_point(severity="critical")])
    inspector = make_inspector()
    provider = MockVLMProvider(
        scripted={"missing_rhinestone": "fail"},
        capture_acceptable=False,
        capture_issues=["blur"],
    )
    result = run_inspection(make_request(), pack, inspector, provider=provider)
    assert result.overall_result == "fail"
