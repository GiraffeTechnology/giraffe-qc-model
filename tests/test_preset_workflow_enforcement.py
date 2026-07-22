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


def _publish_marker(db, sku, revision_id: str, revision_no: int = 1):
    from src.db.studio_models import QCPublishBundle

    db.add(
        QCPublishBundle(
            id="test-bundle-" + revision_id,
            tenant_id=TENANT,
            sku_id=sku.id,
            standard_revision_id=revision_id,
            revision_no=revision_no,
            manifest_json={"test_fixture": True},
            bundle_hash="0" * 64,
            signature="test-signature",
        )
    )
    db.commit()


def test_pad_finalize_records_probation_pair(db_session, job_with_media):
    """PRD §3.2: a probation revision records (ai, human, agreed) per job."""
    from src.inspection.probation_bridge import record_probation_outcome
    from src.qc_model.qualification import probation as _probation

    job = job_with_media
    probation = _probation.start_probation(
        db_session,
        standard_revision_id=job.active_standard_revision_id,
        tenant_id=TENANT,
        sku_id=job.sku_id,
    )

    points = get_active_detection_points_for_job(db_session, job.id, tenant_id=TENANT)
    # AI suggests fail on the first point; the operator overrides to pass.
    suggestions = [
        {"point_code": p.point_code, "result": "fail" if i == 0 else "pass"}
        for i, p in enumerate(points)
    ]
    from src.db.execution_models import QCModelResult

    db_session.add(
        QCModelResult(
            id="mr-1",
            job_id=job.id,
            tenant_id=TENANT,
            provider="test",
            model_name="test-vlm",
            raw_output={
                "mode": "operator_review_suggestions",
                "checkpoint_results": suggestions,
            },
        )
    )
    db_session.commit()

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
    report = finalize_job(
        db_session, job.id, tenant_id=TENANT, require_human_review=True
    )
    assert report.overall_result == "pass"

    recorded = record_probation_outcome(db_session, job, report, TENANT)
    assert recorded is not None
    assert recorded["ai_verdict"] == "fail"
    assert recorded["human_final_verdict"] == "pass"
    assert recorded["agreed"] is False
    assert recorded["jobs_recorded"] == 1
    assert any(
        d["point_code"] == points[0].point_code
        for d in recorded["point_disagreements"]
    )

    # Idempotent: the same job cannot be recorded twice (job_ref dedup).
    assert record_probation_outcome(db_session, job, report, TENANT) is None

    refreshed = _probation.get_probation(db_session, probation.id, TENANT)
    assert refreshed.jobs_recorded == 1
    assert refreshed.agreements == 0


def test_probation_not_recorded_without_ai_suggestions(db_session, job_with_media):
    """No AI ran → no (ai, human) pair exists → nothing recorded."""
    from src.inspection.probation_bridge import record_probation_outcome
    from src.qc_model.qualification import probation as _probation

    job = job_with_media
    _probation.start_probation(
        db_session,
        standard_revision_id=job.active_standard_revision_id,
        tenant_id=TENANT,
        sku_id=job.sku_id,
    )
    points = get_active_detection_points_for_job(db_session, job.id, tenant_id=TENANT)
    submit_checkpoint_results_batch(
        db_session,
        job.id,
        [
            {"detection_point_id": p.id, "result": "pass", "confidence": 0.9}
            for p in points
        ],
        tenant_id=TENANT,
        reviewed_by="operator-7",
    )
    report = finalize_job(
        db_session, job.id, tenant_id=TENANT, require_human_review=True
    )
    assert record_probation_outcome(db_session, job, report, TENANT) is None


def test_lifecycle_view_follows_prd_state_chain(db_session):
    from src.inspection.workflow import derive_standard_lifecycle
    from src.qc_model.qualification import probation as _probation

    sku = seed_shirt_custom(db_session, tenant_id=TENANT)
    state = derive_standard_lifecycle(db_session, sku.id, TENANT)
    assert state["stage"] == "confirmed"
    revision_id = state["standard_revision_id"]

    _publish_marker(db_session, sku, revision_id)
    assert derive_standard_lifecycle(db_session, sku.id, TENANT)["stage"] == "published"

    probation = _probation.start_probation(
        db_session, standard_revision_id=revision_id, tenant_id=TENANT, sku_id=sku.id
    )
    assert derive_standard_lifecycle(db_session, sku.id, TENANT)["stage"] == "probation"

    probation.status = _probation.PROBATION_QUALIFIED
    db_session.commit()
    assert (
        derive_standard_lifecycle(db_session, sku.id, TENANT)["stage"]
        == "active_inspection"
    )


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
