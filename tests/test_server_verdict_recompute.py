"""S4 — Server verdict recompute unit tests (§9, §16.4).

These hit the pure recompute core directly — no UI, no DB — exactly as the spec
requires so Session 7's security tests can reuse them.
"""
from __future__ import annotations

from src.qc_model.verdict.recompute import (
    FAIL,
    PASS,
    REVIEW_REQUIRED,
    PadSubmission,
    StandardRevisionSpec,
    SubmittedCheckpoint,
    recompute_verdict,
)


def _spec(required=("cp1", "cp2"), critical=(), bundle="1.0.0", known=True):
    return StandardRevisionSpec(
        revision_id="rev1",
        bundle_version=bundle,
        required_checkpoint_ids=frozenset(required),
        critical_checkpoint_ids=frozenset(critical),
        known=known,
    )


def _submission(checkpoints, pad="pass", bundle="1.0.0", rev="rev1"):
    return PadSubmission(
        job_ref="job1",
        standard_revision_id=rev,
        bundle_version=bundle,
        pad_overall_result=pad,
        checkpoints=tuple(SubmittedCheckpoint(c, r) for c, r in checkpoints),
    )


def test_all_pass_is_pass_and_agrees():
    sub = _submission([("cp1", "pass"), ("cp2", "pass")], pad="pass")
    v = recompute_verdict(sub, _spec())
    assert v.server_overall_result == PASS
    assert v.agrees is True
    assert v.differences == []


def test_pass_with_failed_checkpoint_recomputed_fail():
    # Pad LIES: claims pass while a checkpoint failed.
    sub = _submission([("cp1", "pass"), ("cp2", "fail")], pad="pass")
    v = recompute_verdict(sub, _spec())
    assert v.server_overall_result == FAIL
    assert v.agrees is False
    assert "cp2" in v.failing_checkpoints
    assert "pad_claimed_pass_overridden" in v.warnings
    assert v.rule_applied == "checkpoint_failed"


def test_pass_with_missing_checkpoint_cannot_be_pass():
    # cp2 required but never reported.
    sub = _submission([("cp1", "pass")], pad="pass")
    v = recompute_verdict(sub, _spec())
    assert v.server_overall_result == REVIEW_REQUIRED
    assert v.missing_checkpoints == ["cp2"]
    assert v.rule_applied == "missing_required_checkpoint"
    assert v.agrees is False


def test_non_passing_checkpoint_cannot_be_pass():
    sub = _submission([("cp1", "pass"), ("cp2", "low_confidence")], pad="pass")
    v = recompute_verdict(sub, _spec())
    assert v.server_overall_result == REVIEW_REQUIRED
    assert v.rule_applied == "non_passing_checkpoint"


def test_unknown_standard_revision_fails_closed():
    sub = _submission([("cp1", "pass"), ("cp2", "pass")], pad="pass")
    v = recompute_verdict(sub, None)
    assert v.server_overall_result == REVIEW_REQUIRED
    assert v.rule_applied == "unknown_standard_revision"
    assert "unknown_standard_revision" in v.warnings


def test_unknown_flag_on_spec_also_fails_closed():
    sub = _submission([("cp1", "pass"), ("cp2", "pass")], pad="pass")
    v = recompute_verdict(sub, _spec(known=False))
    assert v.server_overall_result == REVIEW_REQUIRED
    assert v.rule_applied == "unknown_standard_revision"


def test_bundle_version_mismatch_is_review_required():
    sub = _submission([("cp1", "pass"), ("cp2", "pass")], pad="pass", bundle="2.0.0")
    v = recompute_verdict(sub, _spec(bundle="1.0.0"))
    assert v.server_overall_result == REVIEW_REQUIRED
    assert v.rule_applied == "bundle_version_mismatch"
    assert any(w.startswith("bundle_version_mismatch") for w in v.warnings)


def test_critical_fail_flagged():
    sub = _submission([("cp1", "fail"), ("cp2", "pass")], pad="fail")
    v = recompute_verdict(sub, _spec(critical=("cp1",)))
    assert v.server_overall_result == FAIL
    assert "critical_checkpoint_failed" in v.warnings
    assert v.agrees is True  # pad also said fail


def test_fail_outranks_missing():
    # cp1 failed, cp2 missing → still a fail (observed defect dominates).
    sub = _submission([("cp1", "fail")], pad="review_required")
    v = recompute_verdict(sub, _spec())
    assert v.server_overall_result == FAIL
    assert v.missing_checkpoints == ["cp2"]


def test_unknown_checkpoint_result_value_warned_and_non_pass():
    sub = _submission([("cp1", "pass"), ("cp2", "banana")], pad="pass")
    v = recompute_verdict(sub, _spec())
    assert v.server_overall_result == REVIEW_REQUIRED
    assert any(w.startswith("unknown_checkpoint_result") for w in v.warnings)


def test_pad_fail_but_server_pass_still_recorded_as_difference():
    # Pad over-rejected; server sees all pass. Difference is recorded either way.
    sub = _submission([("cp1", "pass"), ("cp2", "pass")], pad="fail")
    v = recompute_verdict(sub, _spec())
    assert v.server_overall_result == PASS
    assert v.agrees is False
    assert v.differences == ["pad=fail server=pass"]
    # not a pass->override, so no override warning
    assert "pad_claimed_pass_overridden" not in v.warnings
