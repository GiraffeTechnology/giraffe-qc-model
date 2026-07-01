"""Operator requirement structuring tests (PRD §18.2)."""
from __future__ import annotations

from tests.qc_learning_helpers import (
    OPERATOR_REQUIREMENT_TEXT,
    new_session,
    seed_sku,
)

from src.qc_model.learning import service
from src.qc_model.learning.providers.mock_provider import MockRuleLearningProvider


def _run(db):
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    return service.run_learning(db, job.id, provider=MockRuleLearningProvider())


def test_requirements_are_structured_into_expected_proposals():
    db = new_session()
    job = _run(db)
    by_code = {p.proposed_code: p for p in service.list_detection_point_proposals(db, job.id)}

    assert "flower_center_alignment" in by_code
    assert by_code["flower_center_alignment"].proposed_checkpoint_category == "visual_defect"

    assert "chain_link_count" in by_code
    assert by_code["chain_link_count"].proposed_checkpoint_category == "physical_measurement"

    assert "petal_crack" in by_code
    assert by_code["petal_crack"].proposed_checkpoint_category == "visual_defect"


def test_all_proposals_require_supervisor_confirmation():
    db = new_session()
    job = _run(db)
    proposals = service.list_detection_point_proposals(db, job.id)
    assert proposals  # non-empty
    # Every proposal starts in 'proposed' and none is auto-approved/applied.
    assert all(p.status == "proposed" for p in proposals)
    # Report says supervisor review required and cannot auto-apply.
    report = service.get_report(db, job.id)
    assert report["requires_supervisor_review"] is True
    assert report["can_apply_to_training_pack"] is False


def test_source_requirement_is_preserved():
    db = new_session()
    job = _run(db)
    for p in service.list_detection_point_proposals(db, job.id):
        assert p.source_requirement  # each proposal keeps its origin text


def test_visual_defect_gets_primary_role_and_physical_gets_record_only():
    db = new_session()
    job = _run(db)
    by_code = {p.proposed_code: p for p in service.list_detection_point_proposals(db, job.id)}
    assert by_code["flower_center_alignment"].proposed_ai_role == "primary_visual_judge"
    assert by_code["chain_link_count"].proposed_ai_role == "record_only"
