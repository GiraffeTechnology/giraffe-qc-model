"""Learning report audit tests (PRD §7.3, §18.5)."""
from __future__ import annotations

from tests.qc_learning_helpers import (
    OPERATOR_REQUIREMENT_TEXT,
    new_session,
    seed_sku,
)

from src.qc_model.learning import service
from src.qc_model.learning.providers.mock_provider import MockRuleLearningProvider


def test_report_records_required_audit_fields():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, OPERATOR_REQUIREMENT_TEXT)
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider())

    report = service.get_report(db, job.id)
    for field in (
        "provider",
        "model",
        "runtime_profile",
        "training_pack_id",
        "sku_id",
        "station_id",
        "input_summary",
        "detection_point_proposals",
        "uncertainties",
        "requires_supervisor_review",
        "can_apply_to_training_pack",
    ):
        assert field in report, f"missing report field: {field}"

    assert report["runtime_profile"] == "server"
    assert report["model"] == "mock-rule-learning-v1"
    assert report["requires_supervisor_review"] is True
    assert report["can_apply_to_training_pack"] is False


def test_report_input_summary_counts_inputs():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, "Check petal cracks")
    service.add_sample_refs(db, job.id, {"defect_samples": ["d1.png", "d2.png"], "boundary_samples": ["b1.png"]})
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider())

    report = service.get_report(db, job.id)
    assert report["input_summary"]["operator_requirement_count"] == 1
    assert report["input_summary"]["defect_samples"] == 2
    assert report["input_summary"]["boundary_samples"] == 1


def test_physical_measurement_warnings_recorded():
    db = new_session()
    seed_sku(db)
    job = service.create_learning_job(db, "tp1", "sku1", "st1")
    service.add_operator_requirement(db, job.id, "Verify chain link count")
    job = service.run_learning(db, job.id, provider=MockRuleLearningProvider())
    report = service.get_report(db, job.id)
    assert any("chain_link_count" in w for w in report["physical_measurement_warnings"])
