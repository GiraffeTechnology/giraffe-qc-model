"""Learning job state machine tests (PRD §11, §18)."""
from __future__ import annotations

from tests.qc_learning_helpers import (
    OPERATOR_REQUIREMENT_TEXT,
    new_session,
    seed_sku,
)

from src.qc_model.learning import service
from src.qc_model.learning.providers.mock_provider import MockRuleLearningProvider
from src.qc_model.learning.schemas import LearningJobStatus


def test_new_job_is_draft():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    assert job.status == LearningJobStatus.DRAFT.value


def test_adding_requirement_moves_to_input_ready():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, "Check petal cracks")
    job = service.get_job(db, job.id)
    assert job.status == LearningJobStatus.INPUT_READY.value


def test_run_moves_to_proposed():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider())
    assert job.status == LearningJobStatus.PROPOSED.value


def test_approve_all_moves_to_approved_then_apply_moves_to_applied():
    from src.qc_model.learning import apply

    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider())
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]

    job = service.approve_proposals(db, job.id, ids, "sup1")
    assert job.status == LearningJobStatus.APPROVED.value

    result = apply.apply_approved_rules(db, job.id, "sup1")
    assert result["job_status"] == LearningJobStatus.APPLIED.value


def test_partial_approval_status():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider())
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]

    job = service.approve_proposals(db, job.id, ids[:1], "sup1")
    assert job.status == LearningJobStatus.PARTIALLY_APPROVED.value


def test_reject_all_moves_to_rejected():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider())
    ids = [p.id for p in service.list_detection_point_proposals(db, job.id)]

    job = service.reject_proposals(db, job.id, ids, "sup1")
    assert job.status == LearningJobStatus.REJECTED.value


def test_invalid_output_moves_to_failed():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider(valid=False))
    assert job.status == LearningJobStatus.FAILED.value
