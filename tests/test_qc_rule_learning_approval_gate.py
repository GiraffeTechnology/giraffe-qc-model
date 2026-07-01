"""Approval gate tests (PRD §17, §18.4)."""
from __future__ import annotations

from tests.qc_learning_helpers import (
    OPERATOR_REQUIREMENT_TEXT,
    new_session,
    seed_sku,
)

from src.qc_model.learning import apply, service
from src.qc_model.learning.providers.mock_provider import MockRuleLearningProvider


def _proposed_job(db):
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    return service.run_learning(db, job.id, provider=MockRuleLearningProvider())


def test_unapproved_proposals_cannot_be_applied():
    db = new_session()
    job = _proposed_job(db)
    # Apply without approving anything.
    result = apply.apply_approved_rules(db, job.id, "sup1")
    assert result["applied_proposal_ids"] == []
    assert all(s["reason"].startswith("not_approved") for s in result["skipped"])


def test_rejected_proposals_cannot_be_applied():
    db = new_session()
    job = _proposed_job(db)
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]
    service.reject_proposals(db, job.id, ids, "sup1")
    result = apply.apply_approved_rules(db, job.id, "sup1")
    assert result["applied_proposal_ids"] == []


def test_approved_proposals_can_be_applied():
    db = new_session()
    job = _proposed_job(db)
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]
    service.approve_proposals(db, job.id, ids, "sup1")
    result = apply.apply_approved_rules(db, job.id, "sup1")
    assert len(result["applied_proposal_ids"]) == len(ids)


def test_applied_proposals_preserve_approval_metadata():
    db = new_session()
    job = _proposed_job(db)
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]
    service.approve_proposals(db, job.id, ids, "sup_alice")
    apply.apply_approved_rules(db, job.id, "sup_bob")
    for p in service.list_detection_point_proposals(db, job.id):
        assert p.status == "applied"
        assert p.approved_by == "sup_alice"
        assert p.approved_at is not None
        assert p.applied_detection_point_id is not None


def test_applying_does_not_auto_activate_training_pack():
    db = new_session()
    job = _proposed_job(db)
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]
    service.approve_proposals(db, job.id, ids, "sup1")
    result = apply.apply_approved_rules(db, job.id, "sup1")
    assert result["training_pack_auto_activated"] is False


def test_apply_is_idempotent():
    db = new_session()
    job = _proposed_job(db)
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]
    service.approve_proposals(db, job.id, ids, "sup1")
    first = apply.apply_approved_rules(db, job.id, "sup1")
    second = apply.apply_approved_rules(db, job.id, "sup1")
    assert len(first["applied_proposal_ids"]) == len(ids)
    assert second["applied_proposal_ids"] == []

    # Only one detection point per proposal was created.
    from src.db.sku_models import QCDetectionPoint

    dps = db.query(QCDetectionPoint).filter_by(sku_id="sku1").all()
    assert len(dps) == len(ids)


def test_category_edit_during_approval_recomputes_ai_role():
    """Editing a proposal's category must re-derive its AI role (P1 fix).

    A supervisor correcting a visual proposal to physical_measurement must not
    leave a stale primary_visual_judge role that apply() would persist.
    """
    db = new_session()
    job = _proposed_job(db)
    visual = next(
        p for p in service.list_detection_point_proposals(db, job.id)
        if p.proposed_checkpoint_category == "visual_defect"
    )
    service.approve_proposals(
        db, job.id, [visual.id], "sup1",
        edits={visual.id: {"proposed_checkpoint_category": "physical_measurement"}},
    )
    apply.apply_approved_rules(db, job.id, "sup1")

    from src.db.sku_models import QCDetectionPoint

    dp = (
        db.query(QCDetectionPoint)
        .filter_by(sku_id="sku1", point_code=visual.proposed_code)
        .first()
    )
    # Corrected to physical_measurement → AI role must be record_only.
    assert dp.method_hint == "record_only"


def test_apply_on_empty_job_does_not_mark_applied():
    """Applying a job with no proposals must not falsely mark it applied (P2)."""
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    result = apply.apply_approved_rules(db, job.id, "sup1")
    assert result["applied_proposal_ids"] == []
    assert result["job_status"] != "applied"


def test_applied_detection_point_traceability_and_category():
    db = new_session()
    job = _proposed_job(db)
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]
    service.approve_proposals(db, job.id, ids, "sup1")
    apply.apply_approved_rules(db, job.id, "sup1")

    from src.db.qc_model_models import QCCheckpointClassification
    from src.db.sku_models import QCDetectionPoint

    # Physical measurement stays record-only (never AI-primary).
    physical_dp = (
        db.query(QCDetectionPoint)
        .filter_by(sku_id="sku1", point_code="chain_link_count")
        .first()
    )
    assert physical_dp is not None
    classification = (
        db.query(QCCheckpointClassification)
        .filter_by(detection_point_id=physical_dp.id)
        .first()
    )
    assert classification.confirmed_checkpoint_category == "physical_measurement"
    assert "learning job" in classification.classification_rationale
