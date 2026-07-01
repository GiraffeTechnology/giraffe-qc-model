"""VLM sample-learning tests (PR 23 §7)."""
from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["QC_SAMPLE_LEARNING_ALLOW_MOCK"] = "true"

from src.db.models import Base
import src.db.sku_models  # noqa: F401
import src.db.qc_sample_learning_models  # noqa: F401
from src.api.deps import get_db_dep
from src.api.main import app
from src.db.sku_models import QCDetectionPoint, QCSkuItem


def _uid() -> str:
    return uuid.uuid4().hex


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
def client(session_factory):
    def override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db_dep] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def dp(session_factory):
    """Seed a detection point for tenant 'default' and one for tenant 'other'."""
    s = session_factory()
    sku_id = _uid()
    s.add(QCSkuItem(id=sku_id, tenant_id="default", item_number="X", name="X"))
    dp_id = _uid()
    s.add(QCDetectionPoint(id=dp_id, tenant_id="default", sku_id=sku_id, point_code="glue_overflow", label="Glue", severity="major"))
    other_sku = _uid()
    s.add(QCSkuItem(id=other_sku, tenant_id="other", item_number="Y", name="Y"))
    other_dp = _uid()
    s.add(QCDetectionPoint(id=other_dp, tenant_id="other", sku_id=other_sku, point_code="x", label="x", severity="major"))
    s.commit()
    s.close()
    return {"dp_id": dp_id, "other_dp": other_dp}


def _make_group(client, dp_id, sample_type="defect", tp="tp1", tenant="default", refs=None):
    refs = refs if refs is not None else ["s3://a.jpg", "s3://b.jpg"]
    return client.post(
        f"/api/qc/training-packs/{tp}/sample-groups",
        json={"detection_point_id": dp_id, "sample_type": sample_type,
              "image_references": refs, "tenant_id": tenant},
    )


def _learn(client, group_id, tp="tp1", tenant="default"):
    return client.post(
        f"/api/qc/training-packs/{tp}/sample-learning-jobs",
        json={"sample_group_id": group_id, "tenant_id": tenant},
    ).json()


# ── Sample group creation + validation ────────────────────────────────────


@pytest.mark.parametrize("stype", ["reference", "positive", "defect", "boundary", "capture_artifact"])
def test_create_group_all_sample_types(client, dp, stype):
    resp = _make_group(client, dp["dp_id"], sample_type=stype, tp=f"tp_{stype}")
    assert resp.status_code == 201
    assert resp.json()["sample_type"] == stype
    assert len(resp.json()["samples"]) == 2


def test_invalid_sample_type_rejected(client, dp):
    resp = _make_group(client, dp["dp_id"], sample_type="not_a_type")
    assert resp.status_code == 422


def test_detection_point_cross_tenant_rejected(client, dp):
    # tenant 'default' cannot use tenant 'other''s detection point.
    resp = client.post(
        "/api/qc/training-packs/tpX/sample-groups",
        json={"detection_point_id": dp["other_dp"], "sample_type": "defect", "tenant_id": "default"},
    )
    assert resp.status_code == 404


# ── Learning per sample type populates the right fields ───────────────────


def test_reference_learning_produces_observations(client, dp):
    g = _make_group(client, dp["dp_id"], "reference", tp="tp_ref").json()
    job = _learn(client, g["sample_group_id"], tp="tp_ref")
    assert job["status"] == "completed" and job["observation_count"] == 2
    obs = client.get(f"/api/qc/sample-learning-jobs/{job['job_id']}/observations").json()["observations"]
    assert all(o["feature_type"] == "normal_feature" for o in obs)
    assert any(o["normal_visual_features"] for o in obs)


def test_defect_learning_populates_defect_features(client, dp):
    g = _make_group(client, dp["dp_id"], "defect", tp="tp_def").json()
    job = _learn(client, g["sample_group_id"], tp="tp_def")
    obs = client.get(f"/api/qc/sample-learning-jobs/{job['job_id']}/observations").json()["observations"]
    assert all(o["defect_visual_features"] for o in obs)


def test_boundary_learning_populates_acceptable_variations(client, dp):
    g = _make_group(client, dp["dp_id"], "boundary", tp="tp_bnd").json()
    job = _learn(client, g["sample_group_id"], tp="tp_bnd")
    obs = client.get(f"/api/qc/sample-learning-jobs/{job['job_id']}/observations").json()["observations"]
    assert all(o["acceptable_variations"] for o in obs)


def test_capture_artifact_learning_populates_risks(client, dp):
    g = _make_group(client, dp["dp_id"], "capture_artifact", tp="tp_cap").json()
    job = _learn(client, g["sample_group_id"], tp="tp_cap")
    obs = client.get(f"/api/qc/sample-learning-jobs/{job['job_id']}/observations").json()["observations"]
    assert all(o["capture_artifact_risks"] for o in obs)


def test_observation_preserves_all_provenance_fields(client, dp):
    g = _make_group(client, dp["dp_id"], "defect", tp="tp_prov").json()
    job = _learn(client, g["sample_group_id"], tp="tp_prov")
    obs = client.get(f"/api/qc/sample-learning-jobs/{job['job_id']}/observations").json()["observations"]
    sample_ids = {s["sample_id"] for s in g["samples"]}
    for o in obs:
        for field in ("source_sample_id", "image_reference", "detection_point_code",
                      "feature_type", "confidence", "uncertainty", "rule_implication",
                      "requires_human_review"):
            assert field in o
        assert o["source_sample_id"] in sample_ids  # traceable to the exact sample


# ── Approve → apply (two distinct steps, server-side gated) ────────────────


def _proposed_memory(client, dp, tp):
    g = _make_group(client, dp["dp_id"], "defect", tp=tp).json()
    job = _learn(client, g["sample_group_id"], tp=tp)
    mem = client.get(f"/api/qc/sample-learning-jobs/{job['job_id']}/visual-rule-memory").json()["visual_rule_memory"]
    return mem[0]["memory_id"]


def test_unapproved_memory_apply_is_rejected(client, dp):
    mid = _proposed_memory(client, dp, "tp_unappr")
    resp = client.post(
        "/api/qc/training-packs/tp_unappr/apply-approved-visual-rule-memory",
        json={"memory_id": mid, "applied_by": "sup"},
    )
    assert resp.status_code == 409


def test_approved_memory_apply_succeeds_and_links(client, dp):
    mid = _proposed_memory(client, dp, "tp_appr")
    client.post(f"/api/qc/visual-rule-memory/{mid}/approval", json={"action": "approve", "reviewer_id": "sup"})
    resp = client.post(
        "/api/qc/training-packs/tp_appr/apply-approved-visual-rule-memory",
        json={"memory_id": mid, "applied_by": "sup"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_memory_id"] == mid
    assert body["training_pack_id"] == "tp_appr"


def test_conflicting_apply_is_rejected_no_silent_overwrite(client, dp, session_factory):
    from src.db.qc_sample_learning_models import QCConfirmedVisualRule, VisualRuleMemory

    # First approved memory applied for (tp, detection point, feature_type).
    mid1 = _proposed_memory(client, dp, "tp_conflict")
    client.post(f"/api/qc/visual-rule-memory/{mid1}/approval", json={"action": "approve", "reviewer_id": "sup"})
    client.post("/api/qc/training-packs/tp_conflict/apply-approved-visual-rule-memory",
                json={"memory_id": mid1, "applied_by": "sup"})

    # A second, different approved memory for the same key, with different content.
    mid2 = _proposed_memory(client, dp, "tp_conflict")
    s = session_factory()
    try:
        m2 = s.query(VisualRuleMemory).filter_by(id=mid2).first()
        m2.defect_visual_features_json = ["a totally different confirmed defect signature"]
        m2.status = "approved"
        s.commit()
    finally:
        s.close()
    resp = client.post("/api/qc/training-packs/tp_conflict/apply-approved-visual-rule-memory",
                       json={"memory_id": mid2, "applied_by": "sup"})
    assert resp.status_code == 409
    # No silent overwrite: only one confirmed rule for that key.
    s = session_factory()
    try:
        count = s.query(QCConfirmedVisualRule).filter_by(
            training_pack_id="tp_conflict", detection_point_code="glue_overflow", feature_type="defect_feature"
        ).count()
        assert count == 1
    finally:
        s.close()


# ── Fail-closed ───────────────────────────────────────────────────────────


def test_provider_failure_fails_closed(client, dp, session_factory):
    from src.qc_model.sample_learning import service
    from src.qc_model.sample_learning.provider import MockSampleLearningProvider
    from src.db.qc_sample_learning_models import VisualRuleMemory, VisualFeatureObservation

    g = _make_group(client, dp["dp_id"], "defect", tp="tp_fail").json()
    s = session_factory()
    try:
        job = service.run_sample_learning_job(
            s, g["sample_group_id"], provider=MockSampleLearningProvider(valid=False)
        )
        assert job.status == "failed"
        assert s.query(VisualFeatureObservation).filter_by(sample_learning_job_id=job.id).count() == 0
        assert s.query(VisualRuleMemory).filter_by(sample_learning_job_id=job.id).count() == 0
    finally:
        s.close()


def test_malformed_output_fails_closed(client, dp, session_factory):
    from src.qc_model.sample_learning import service
    from src.qc_model.sample_learning.provider import MockSampleLearningProvider

    g = _make_group(client, dp["dp_id"], "defect", tp="tp_malformed").json()
    s = session_factory()
    try:
        # Observation missing required provenance (no source_sample_id).
        bad = MockSampleLearningProvider(raw_override=[{"feature_type": "defect_feature"}])
        job = service.run_sample_learning_job(s, g["sample_group_id"], provider=bad)
        assert job.status == "failed"
    finally:
        s.close()


# ── Tenant isolation ──────────────────────────────────────────────────────


def test_tenant_isolation_on_job_and_observations(client, dp):
    g = _make_group(client, dp["dp_id"], "defect", tp="tp_iso", tenant="default").json()
    job = _learn(client, g["sample_group_id"], tp="tp_iso", tenant="default")
    # Another tenant cannot read the job or its observations.
    assert client.get(f"/api/qc/sample-learning-jobs/{job['job_id']}?tenant_id=intruder").status_code == 404
    assert client.get(
        f"/api/qc/sample-learning-jobs/{job['job_id']}/observations?tenant_id=intruder"
    ).status_code == 404


# ── UI smoke ──────────────────────────────────────────────────────────────


def test_ui_panel_smoke(client, dp):
    tp = "tp_ui"
    # One group left proposed (shows Approve/Reject); one approved (shows Apply).
    g1 = _make_group(client, dp["dp_id"], "boundary", tp=tp).json()
    _learn(client, g1["sample_group_id"], tp=tp)

    g2 = _make_group(client, dp["dp_id"], "defect", tp=tp).json()
    job2 = _learn(client, g2["sample_group_id"], tp=tp)
    mem2 = client.get(
        f"/api/qc/sample-learning-jobs/{job2['job_id']}/visual-rule-memory"
    ).json()["visual_rule_memory"][0]["memory_id"]
    client.post(f"/api/qc/visual-rule-memory/{mem2}/approval", json={"action": "approve", "reviewer_id": "sup"})

    page = client.get(f"/admin/qc-model/training-packs/{tp}/sample-learning")
    assert page.status_code == 200
    body = page.text
    assert "VLM Sample Learning" in body
    assert "Run sample learning" in body
    assert "Approve" in body  # proposed memory
    assert "Apply to Training Pack" in body  # approved memory
