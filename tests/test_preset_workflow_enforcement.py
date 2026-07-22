"""The preset Stage 2 operator workflow is enforced, not advisory:

* a model can never finalize its own pass — the operator flow requires a
  human-reviewed result for every checkpoint before a pass verdict;
* checkpoint results record their provenance (operator vs model) and reviewer;
* the workflow endpoint exposes which ordered steps are done, so a skipped
  step is visible instead of silent.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_models  # noqa: F401
import src.db.sku_models  # noqa: F401
import src.db.execution_models  # noqa: F401
import src.db.intake_models  # noqa: F401
import src.db.pad_models  # noqa: F401
from src.db.seed_data import seed_shirt_custom
from src.inspection.api_service import (
    attach_inspection_media,
    create_inspection_job_from_api,
    ingest_model_output,
)
from src.inspection.service import (
    finalize_job,
    get_active_detection_points_for_job,
    submit_checkpoint_results_batch,
)
from src.inspection.workflow import derive_workflow_state

TENANT = "demo"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def job_with_media(db_session):
    sku = seed_shirt_custom(db_session, tenant_id=TENANT)
    job = create_inspection_job_from_api(
        db_session, sku_id=sku.id, tenant_id=TENANT, created_by="op-1"
    )
    attach_inspection_media(
        db_session, job.id, local_path="/tmp/evidence.jpg", tenant_id=TENANT
    )
    return job


def _model_pass_payload(db, job):
    points = get_active_detection_points_for_job(db, job.id, tenant_id=TENANT)
    return {
        "checkpoint_results": [
            {"point_code": p.point_code, "result": "pass", "confidence": 0.99}
            for p in points
        ],
        "incidental_findings": [],
    }


def test_model_only_results_cannot_finalize_pass(db_session, job_with_media):
    job = job_with_media
    ingest_model_output(
        db_session,
        job.id,
        provider="test",
        model_name="test-vlm",
        raw_output=_model_pass_payload(db_session, job),
        tenant_id=TENANT,
    )
    report = finalize_job(
        db_session, job.id, tenant_id=TENANT, require_human_review=True
    )
    assert report.overall_result == "review_required"
    assert "Operator review incomplete" in report.summary_text


def test_legacy_machine_path_keeps_existing_policy(db_session, job_with_media):
    """The v1 machine API (human gate lives at the L2 verdict layer) is unchanged."""
    job = job_with_media
    ingest_model_output(
        db_session,
        job.id,
        provider="test",
        model_name="test-vlm",
        raw_output=_model_pass_payload(db_session, job),
        tenant_id=TENANT,
    )
    report = finalize_job(db_session, job.id, tenant_id=TENANT)
    assert report.overall_result == "pass"


def test_operator_reviewed_results_finalize_pass(db_session, job_with_media):
    job = job_with_media
    points = get_active_detection_points_for_job(db_session, job.id, tenant_id=TENANT)
    rows = submit_checkpoint_results_batch(
        db_session,
        job.id,
        [
            {"detection_point_id": p.id, "result": "pass", "confidence": 0.97}
            for p in points
        ],
        tenant_id=TENANT,
        reviewed_by="operator-7",
    )
    assert all(r.review_source == "operator" for r in rows)
    assert all(r.reviewed_by == "operator-7" for r in rows)
    report = finalize_job(
        db_session, job.id, tenant_id=TENANT, require_human_review=True
    )
    assert report.overall_result == "pass"


def test_model_derived_results_are_marked_model(db_session, job_with_media):
    job = job_with_media
    ingest_model_output(
        db_session,
        job.id,
        provider="test",
        model_name="test-vlm",
        raw_output=_model_pass_payload(db_session, job),
        tenant_id=TENANT,
    )
    from src.db.execution_models import QCCheckpointResult

    rows = db_session.query(QCCheckpointResult).filter_by(job_id=job.id).all()
    assert rows and all(r.review_source == "model" for r in rows)
    assert all(r.reviewed_by is None for r in rows)


def test_workflow_state_tracks_preset_step_order(db_session):
    sku = seed_shirt_custom(db_session, tenant_id=TENANT)
    job = create_inspection_job_from_api(
        db_session, sku_id=sku.id, tenant_id=TENANT, created_by="op-1"
    )

    state = derive_workflow_state(db_session, job, tenant_id=TENANT)
    assert state["next_step"] == "evidence_attached"
    assert not state["workflow_complete"]

    attach_inspection_media(
        db_session, job.id, local_path="/tmp/evidence.jpg", tenant_id=TENANT
    )
    state = derive_workflow_state(db_session, job, tenant_id=TENANT)
    assert state["next_step"] == "vision_analyzed"

    ingest_model_output(
        db_session,
        job.id,
        provider="test",
        model_name="test-vlm",
        raw_output={"checkpoint_results": [], "incidental_findings": []},
        tenant_id=TENANT,
    )
    state = derive_workflow_state(db_session, job, tenant_id=TENANT)
    assert state["next_step"] == "operator_reviewed"

    points = get_active_detection_points_for_job(db_session, job.id, tenant_id=TENANT)
    submit_checkpoint_results_batch(
        db_session,
        job.id,
        [
            {"detection_point_id": p.id, "result": "pass", "confidence": 0.97}
            for p in points
        ],
        tenant_id=TENANT,
        reviewed_by="operator-7",
    )
    state = derive_workflow_state(db_session, job, tenant_id=TENANT)
    assert state["next_step"] == "finalized"

    finalize_job(db_session, job.id, tenant_id=TENANT, require_human_review=True)
    state = derive_workflow_state(db_session, job, tenant_id=TENANT)
    assert state["workflow_complete"]
    assert [s["step"] for s in state["steps"]] == [
        "standard_active",
        "evidence_attached",
        "vision_analyzed",
        "operator_reviewed",
        "finalized",
    ]
