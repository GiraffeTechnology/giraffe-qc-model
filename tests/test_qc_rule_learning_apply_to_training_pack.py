"""Apply-to-Training-Pack tests (PRD §17, §18.4)."""
from __future__ import annotations

from tests.qc_learning_helpers import (
    OPERATOR_REQUIREMENT_TEXT,
    new_session,
    seed_sku,
)

from src.db.sku_models import QCDetectionPoint
from src.qc_model.learning import apply, service
from src.qc_model.learning.providers.mock_provider import MockRuleLearningProvider


def _approved_job(db):
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider())
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]
    service.approve_proposals(db, job.id, ids, "sup1")
    return job


def test_apply_creates_detection_points_for_sku():
    db = new_session()
    job = _approved_job(db)
    apply.apply_approved_rules(db, job.id, "sup1")
    codes = {
        dp.point_code for dp in db.query(QCDetectionPoint).filter_by(sku_id="sku1").all()
    }
    assert {"flower_center_alignment", "chain_link_count", "petal_crack"} <= codes


def test_applied_detection_points_carry_ai_role_hint():
    db = new_session()
    job = _approved_job(db)
    apply.apply_approved_rules(db, job.id, "sup1")
    by_code = {
        dp.point_code: dp for dp in db.query(QCDetectionPoint).filter_by(sku_id="sku1").all()
    }
    assert by_code["chain_link_count"].method_hint == "record_only"
    assert by_code["flower_center_alignment"].method_hint == "primary_visual_judge"


def test_only_approved_subset_is_applied():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider())
    proposals = service.list_detection_point_proposals(db, job.id)
    # Approve only the visual defect ones; leave physical unapproved.
    approve_ids = [p.id for p in proposals if p.proposed_checkpoint_category == "visual_defect"]
    service.approve_proposals(db, job.id, approve_ids, "sup1")
    result = apply.apply_approved_rules(db, job.id, "sup1")
    assert len(result["applied_proposal_ids"]) == len(approve_ids)

    codes = {dp.point_code for dp in db.query(QCDetectionPoint).filter_by(sku_id="sku1").all()}
    assert "chain_link_count" not in codes  # not approved → not applied
