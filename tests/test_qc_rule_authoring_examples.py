"""Worked-example + missing-info + guard tests (PR 22 §3, §4, §5, §9)."""
from __future__ import annotations

import json

import pytest

from src.qc_model.authoring.classifier import classify_fragment
from src.qc_model.authoring.provider import (
    AuthoringFragmentInput,
    MockRuleAuthoringProvider,
    QCRuleAuthoringRequest,
)
from src.qc_model.authoring.validator import validate_response


# ── §3 Worked examples (literal fixtures) ─────────────────────────────────


def test_example_a_physical_measurement():
    p = classify_fragment("pearl diameter 6mm ± 0.2mm")
    assert p.checkpoint_category == "physical_measurement"
    assert p.ai_role == "record_only"
    assert "gauge" in p.decision_rule and "caliper" in p.decision_rule


def test_example_b_alignment_ambiguous_axis():
    p = classify_fragment("flower center must align with central axis")
    assert p.checkpoint_category in ("visual_defect", "rule_verification")
    # Insufficient visual evidence → ai_role NOT force-set to primary_visual_judge.
    assert p.ai_role != "primary_visual_judge"
    assert p.questions_or_ambiguities  # a question is raised
    joined = " ".join(p.review_required_conditions).lower()
    assert "oblique" in joined and "axis" in joined


def test_example_c_rule_verification_count():
    p = classify_fragment("rhinestone count must be 12")
    assert p.checkpoint_category == "rule_verification"
    assert p.ai_role == "information_extraction"
    assert p.questions_or_ambiguities  # count basis / view unclear


def test_example_d_visual_defect_front_view():
    p = classify_fragment("no visible glue overflow from front view")
    assert p.checkpoint_category == "visual_defect"
    assert p.ai_role == "primary_visual_judge"
    joined = " ".join(p.review_required_conditions).lower()
    assert "shadow" in joined and "reflection" in joined and "blur" in joined


# ── §5 Missing information → question, never a fabricated value ────────────


def _proposal_text_blob(p) -> str:
    """All human-text fields (excludes numeric confidence)."""
    return json.dumps(
        {
            "decision_rule": p.decision_rule,
            "review_required_conditions": p.review_required_conditions,
            "normal": p.normal_visual_features,
            "defect": p.defect_visual_features,
            "pseudo": p.known_pseudo_defects,
            "evidence": p.evidence_required,
            "name": p.proposed_name,
        }
    )


def test_missing_tolerance_produces_question_not_fabricated_value():
    p = classify_fragment("pearl diameter must be correct")
    assert p.checkpoint_category == "physical_measurement"
    assert any("tolerance" in q.lower() or "dimension" in q.lower() for q in p.questions_or_ambiguities)
    # No fabricated tolerance/number anywhere in the human-text fields.
    import re

    assert not re.search(r"±|\d+\s*(mm|cm|°|%)", _proposal_text_blob(p))


def test_missing_count_produces_question_not_fabricated_value():
    p = classify_fragment("rhinestone count must match the reference sample")
    assert p.checkpoint_category == "rule_verification"
    assert any("count" in q.lower() for q in p.questions_or_ambiguities)
    import re

    # No fabricated integer count in the decision rule / features.
    assert not re.search(r"\b\d+\b", _proposal_text_blob(p))


# ── §4 Physical-measurement guard (adversarial) ───────────────────────────


def test_physical_guard_overrides_hostile_llm_ai_role():
    hostile = [
        {
            "source_fragment_id": "f1",
            "proposed_code": "pearl_diameter",
            "checkpoint_category": "physical_measurement",
            "ai_role": "primary_visual_judge",  # malicious / wrong
        }
    ]
    resp = MockRuleAuthoringProvider(raw_override=hostile).author_rules(
        QCRuleAuthoringRequest("tp", "t", [])
    )
    result = validate_response(resp)
    assert result.valid is True
    assert result.proposals[0].ai_role == "record_only"
    assert result.proposals[0].guard_override_note  # override recorded


@pytest.mark.parametrize("bad_role", ["primary_visual_judge", "information_extraction", "assistant_only", ""])
def test_physical_guard_forces_record_only_for_any_role(bad_role):
    raw = [
        {
            "source_fragment_id": "f1",
            "proposed_code": "x",
            "checkpoint_category": "physical_measurement",
            "ai_role": bad_role,
        }
    ]
    resp = MockRuleAuthoringProvider(raw_override=raw).author_rules(QCRuleAuthoringRequest("tp", "t", []))
    result = validate_response(resp)
    assert result.proposals[0].ai_role == "record_only"


# ── §8 Fail-closed ────────────────────────────────────────────────────────


def test_provider_failure_fails_closed():
    resp = MockRuleAuthoringProvider(valid=False).author_rules(QCRuleAuthoringRequest("tp", "t", []))
    result = validate_response(resp)
    assert result.valid is False
    assert result.proposals == []


def test_malformed_proposal_fails_closed():
    # Missing required keys → whole response invalid, no partial proposals.
    raw = [{"proposed_code": "x"}]  # no source_fragment_id / category / ai_role
    resp = MockRuleAuthoringProvider(raw_override=raw).author_rules(QCRuleAuthoringRequest("tp", "t", []))
    result = validate_response(resp)
    assert result.valid is False
    assert result.proposals == []


def test_default_authoring_provider_fails_closed_without_backend(monkeypatch):
    # No mock allowed + no real backend → qwen skeleton fails closed.
    monkeypatch.delenv("QC_AUTHORING_ALLOW_MOCK", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    from src.qc_model.authoring.provider import get_authoring_provider

    provider = get_authoring_provider()
    resp = provider.author_rules(QCRuleAuthoringRequest("tp", "t", []))
    assert resp.valid is False
