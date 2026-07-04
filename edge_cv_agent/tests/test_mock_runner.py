"""Mock runner scenario coverage (§14.3) — no hardware, no network."""
import pytest

from edge_cv_agent.app.cv_pipeline import MockCVError, run_mock_pipeline
from edge_cv_agent.app.live_capture import LiveCaptureTracker


def _job(scenario=None):
    payload = {"image_uri": "storage://input/image001.jpg"}
    if scenario:
        payload["mock_scenario"] = scenario
    return {"cv_job_id": "cv_job_x", "task_type": "defect_candidate_detection", "input_payload": payload}


def test_success_scenario_returns_structured_output():
    out = run_mock_pipeline(_job("success"))
    assert out.result_type == "detection"
    assert out.pass_fail_hint == "needs_human_review"  # evidence, never a verdict
    assert out.measurements["pearl_candidate_count"] == 8
    assert out.evidence_assets[0]["asset_type"] == "annotated_image"


def test_default_scenario_is_success():
    assert run_mock_pipeline(_job()).result_type == "detection"


@pytest.mark.parametrize("scenario", ["timeout", "memory_failure", "model_missing", "model_hash_mismatch"])
def test_failure_scenarios_raise_with_error_code(scenario):
    with pytest.raises(MockCVError) as exc:
        run_mock_pipeline(_job(scenario))
    assert exc.value.error_code == scenario


def test_partial_result_drops_required_field():
    out = run_mock_pipeline(_job("partial_result"))
    assert out.result_type == ""  # service must reject this as invalid schema


def test_invalid_schema_uses_bad_hint():
    out = run_mock_pipeline(_job("invalid_schema"))
    assert out.pass_fail_hint == "definitely_broken"


def test_live_capture_debounce_and_dedup():
    ticks = iter([0.0, 0.0, 0.0, 0.0, 1.0, 100.0, 100.0, 100.0])
    tracker = LiveCaptureTracker(confidence_threshold=0.6, debounce_frames=3, recapture_cooldown_seconds=5.0)
    tracker._now = lambda: next(ticks)

    # Three consecutive stable frames on the same object → capture on the 3rd.
    assert tracker.observe("obj_a", 0.9) is None
    assert tracker.observe("obj_a", 0.9) is None
    assert tracker.observe("obj_a", 0.9) == "obj_a"
    # Immediately after capture → still in cooldown, suppressed.
    assert tracker.observe("obj_a", 0.9) is None
    assert tracker.observe("obj_a", 0.9) is None
    # After the cooldown window a fresh debounce can capture again.
    assert tracker.observe("obj_a", 0.9) is None
    assert tracker.observe("obj_a", 0.9) is None
    assert tracker.observe("obj_a", 0.9) == "obj_a"


def test_live_capture_ignores_low_confidence():
    tracker = LiveCaptureTracker(confidence_threshold=0.6, debounce_frames=2)
    assert tracker.observe("obj_a", 0.2) is None
    assert tracker.observe(None, 0.0) is None
    assert tracker.state == "watching"
