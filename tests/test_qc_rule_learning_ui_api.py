"""Phase 2A learning UI + API integration tests (PRD §13, §14, §18.7)."""
from __future__ import annotations

import os

# Enable the deterministic mock learning provider for the API run path (Phase 2A
# has no real backend). This never implies real visual accuracy.
os.environ["QC_LEARNING_ALLOW_MOCK"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models  # noqa: F401
import src.db.qc_model_models  # noqa: F401
import src.db.qc_learning_models  # noqa: F401
from src.api.deps import get_db_dep
from src.api.main import app
from src.db.sku_models import QCSkuItem


@pytest.fixture(scope="module")
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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


@pytest.fixture(scope="module", autouse=True)
def seed(session_factory):
    s = session_factory()
    if not s.query(QCSkuItem).filter_by(id="sku1").first():
        s.add(QCSkuItem(id="sku1", tenant_id="default", item_number="FL-1", name="Flower Brooch"))
        s.commit()
    s.close()


def _create_and_run(client) -> tuple[str, list[dict]]:
    created = client.post(
        "/api/qc/training-packs/tp1/learning-jobs",
        json={"sku_id": "sku1", "station_id": "st1"},
    ).json()
    job_id = created["learning_job_id"]
    client.post(
        f"/api/qc/learning-jobs/{job_id}/operator-requirements",
        json={"requirement_text": "Check flower center alignment. Verify chain link count."},
    )
    run = client.post(f"/api/qc/learning-jobs/{job_id}/run", json={}).json()
    return job_id, run["detection_point_proposals"]


def test_admin_learning_page_renders(client):
    resp = client.get("/admin/qc-model/learning")
    assert resp.status_code == 200
    assert "QC Rule Learning Engine" in resp.text
    assert "not active" in resp.text.lower()


def test_create_job_and_run_produces_proposals(client):
    job_id, proposals = _create_and_run(client)
    assert job_id
    codes = {p["proposed_code"] for p in proposals}
    assert "flower_center_alignment" in codes
    assert "chain_link_count" in codes
    # Physical measurement proposed as record_only.
    physical = next(p for p in proposals if p["proposed_code"] == "chain_link_count")
    assert physical["proposed_checkpoint_category"] == "physical_measurement"
    assert physical["proposed_ai_role"] == "record_only"


def test_get_job_and_report(client):
    job_id, _ = _create_and_run(client)
    job = client.get(f"/api/qc/learning-jobs/{job_id}").json()
    assert job["status"] == "proposed"
    report = client.get(f"/api/qc/learning-jobs/{job_id}/report").json()
    assert report["requires_supervisor_review"] is True
    assert report["can_apply_to_training_pack"] is False


def test_apply_only_works_for_approved_proposals(client):
    job_id, proposals = _create_and_run(client)
    ids = [p["proposal_id"] for p in proposals]

    # Apply before approval → nothing applied.
    pre = client.post(
        f"/api/qc/learning-jobs/{job_id}/apply-approved-rules",
        json={"applied_by": "sup1"},
    ).json()
    assert pre["applied_proposal_ids"] == []

    # Approve then apply.
    client.post(
        f"/api/qc/learning-jobs/{job_id}/approve-proposals",
        json={"proposal_ids": ids, "reviewer_id": "sup1"},
    )
    post = client.post(
        f"/api/qc/learning-jobs/{job_id}/apply-approved-rules",
        json={"applied_by": "sup1"},
    ).json()
    assert len(post["applied_proposal_ids"]) == len(ids)
    assert post["training_pack_auto_activated"] is False


def test_reject_endpoint(client):
    job_id, proposals = _create_and_run(client)
    ids = [p["proposal_id"] for p in proposals]
    resp = client.post(
        f"/api/qc/learning-jobs/{job_id}/reject-proposals",
        json={"proposal_ids": ids, "reviewer_id": "sup1"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_list_jobs_for_training_pack(client):
    _create_and_run(client)
    resp = client.get("/api/qc/training-packs/tp1/learning-jobs").json()
    assert len(resp["learning_jobs"]) >= 1


def test_unknown_job_returns_404(client):
    assert client.get("/api/qc/learning-jobs/does-not-exist").status_code == 404
