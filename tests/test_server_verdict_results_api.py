"""S4 — Results API + DB integration tests (§9, §16.1).

Exercises the receiving/recompute/display side end to end: submit a Pad verdict,
recompute against the revision the Pad used, persist, and read it back on the
Results surface. Standard-revision spec is resolved from real DB rows.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models  # noqa: F401
import src.db.qc_verdict_models  # noqa: F401
from src.db.sku_models import QCDetectionPoint, QCSkuItem, QCSkuStandardRevision
from src.api.deps import get_db_dep
from src.api.main import app


T1 = "tenant_1"
T2 = "tenant_2"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def _override():
        yield db_session

    app.dependency_overrides[get_db_dep] = _override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _uid():
    return uuid.uuid4().hex


def _seed_revision(db, tenant=T1, codes=("cp1", "cp2"), critical=()):
    sku = QCSkuItem(id=_uid(), tenant_id=tenant, item_number=f"SKU-{_uid()[:6]}", name="Shirt")
    db.add(sku)
    rev = QCSkuStandardRevision(id=_uid(), sku_id=sku.id, tenant_id=tenant, revision_no=1, status="active")
    db.add(rev)
    for c in codes:
        db.add(
            QCDetectionPoint(
                id=_uid(),
                tenant_id=tenant,
                sku_id=sku.id,
                standard_revision_id=rev.id,
                point_code=c,
                label=c,
                severity="critical" if c in critical else "major",
                is_active=True,
            )
        )
    db.commit()
    return rev.id


def _submit(client, rev_id, checkpoints, pad="pass", tenant=T1, bundle="1.0.0"):
    return client.post(
        "/api/qc/results/submissions",
        json={
            "tenant_id": tenant,
            "job_ref": "job-" + _uid()[:6],
            "standard_revision_id": rev_id,
            "bundle_version": bundle,
            "pad_overall_result": pad,
            "checkpoints": [{"checkpoint_id": c, "result": r} for c, r in checkpoints],
        },
    )


def test_submit_all_pass_agrees(client, db_session):
    rev = _seed_revision(db_session)
    resp = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")], pad="pass")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["server_overall_result"] == "pass"
    assert body["agrees"] is True


def test_submit_pass_with_failed_is_recomputed_fail(client, db_session):
    rev = _seed_revision(db_session)
    resp = _submit(client, rev, [("cp1", "pass"), ("cp2", "fail")], pad="pass")
    body = resp.json()
    assert body["server_overall_result"] == "fail"
    assert body["agrees"] is False
    assert "cp2" in body["failing_checkpoints"]


def test_submit_pass_with_missing_is_non_pass(client, db_session):
    rev = _seed_revision(db_session)
    resp = _submit(client, rev, [("cp1", "pass")], pad="pass")
    body = resp.json()
    assert body["server_overall_result"] == "review_required"
    assert body["missing_checkpoints"] == ["cp2"]


def test_unknown_revision_fails_closed(client):
    resp = _submit(client, "does-not-exist", [("cp1", "pass")], pad="pass")
    body = resp.json()
    assert body["server_overall_result"] == "review_required"
    assert body["rule_applied"] == "unknown_standard_revision"


def test_results_list_and_get(client, db_session):
    rev = _seed_revision(db_session)
    sid = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")]).json()["submission_id"]
    listing = client.get("/api/qc/results", params={"tenant_id": T1}).json()
    assert len(listing) == 1
    detail = client.get(f"/api/qc/results/{sid}", params={"tenant_id": T1})
    assert detail.status_code == 200
    assert detail.json()["submission_id"] == sid


def test_human_final_decision_recorded(client, db_session):
    rev = _seed_revision(db_session)
    sid = _submit(client, rev, [("cp1", "pass")], pad="pass").json()["submission_id"]
    resp = client.post(
        f"/api/qc/results/{sid}/final-decision",
        json={"tenant_id": T1, "decision": "reject", "decided_by": "qa1", "comment": "manual"},
    )
    assert resp.status_code == 201
    assert resp.json()["human_final_decision"] == "reject"
    # server verdict itself is unchanged by the human decision
    assert resp.json()["server_overall_result"] == "review_required"


def test_invalid_human_decision_rejected(client, db_session):
    rev = _seed_revision(db_session)
    sid = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")]).json()["submission_id"]
    resp = client.post(
        f"/api/qc/results/{sid}/final-decision",
        json={"tenant_id": T1, "decision": "banana", "decided_by": "qa1"},
    )
    assert resp.status_code == 400


def test_tenant_isolation(client, db_session):
    rev = _seed_revision(db_session, tenant=T1)
    sid = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")], tenant=T1).json()["submission_id"]
    assert client.get("/api/qc/results", params={"tenant_id": T2}).json() == []
    assert client.get(f"/api/qc/results/{sid}", params={"tenant_id": T2}).status_code == 404


def test_admin_results_page_renders(client, db_session):
    rev = _seed_revision(db_session)
    _submit(client, rev, [("cp1", "pass"), ("cp2", "fail")], pad="pass")
    page = client.get("/admin/results", params={"tenant_id": T1})
    assert page.status_code == 200
    assert "Server Verdict" in page.text
