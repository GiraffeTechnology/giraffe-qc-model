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
from src.qc_model.qualification import probation as probation_service


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


# ── Probation wiring (WS7 §1.2): human final decision -> record_probation_job ─


def test_final_decision_records_probation_job_when_revision_is_on_probation(client, db_session):
    """The real result-submission path (POST .../final-decision) must call
    record_probation_job -- not just the standalone service function -- when
    the standard revision it was judged against is on probation."""
    rev = _seed_revision(db_session)
    probation = probation_service.start_probation(db_session, standard_revision_id=rev, tenant_id=T1)

    sid = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")], pad="pass").json()["submission_id"]
    resp = client.post(
        f"/api/qc/results/{sid}/final-decision",
        json={"tenant_id": T1, "decision": "pass", "decided_by": "qa1"},
    )
    assert resp.status_code == 201

    report = client.get(f"/api/qc/probation/{probation.id}/disagreement-report", params={"tenant_id": T1}).json()
    assert report["gate"]["jobs_recorded"] == 1
    assert report["gate"]["agreements"] == 1  # server_overall_result "pass" == human "pass"


def test_final_decision_records_disagreement_on_probation(client, db_session):
    rev = _seed_revision(db_session)
    probation = probation_service.start_probation(db_session, standard_revision_id=rev, tenant_id=T1)

    sid = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")], pad="pass").json()["submission_id"]
    client.post(
        f"/api/qc/results/{sid}/final-decision",
        json={"tenant_id": T1, "decision": "reject", "decided_by": "qa1"},
    )

    p = client.get(f"/api/qc/probation/{probation.id}", params={"tenant_id": T1}).json()
    assert p["gate"]["jobs_recorded"] == 1
    assert p["gate"]["agreements"] == 0  # server said "pass", human said "reject"


def test_final_decision_without_probation_record_is_unaffected(client, db_session):
    """No probation record exists for this revision (never published) --
    recording a human decision must still succeed and must not create one."""
    rev = _seed_revision(db_session)
    sid = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")], pad="pass").json()["submission_id"]
    resp = client.post(
        f"/api/qc/results/{sid}/final-decision",
        json={"tenant_id": T1, "decision": "pass", "decided_by": "qa1"},
    )
    assert resp.status_code == 201
    assert client.get(f"/api/qc/probation/by-revision/{rev}", params={"tenant_id": T1}).status_code == 404


def test_final_decision_skipped_while_probation_paused(client, db_session):
    """A paused probation (admin mid-edit) must not gain jobs from decisions
    made in the meantime -- but the decision itself must still be recorded."""
    rev = _seed_revision(db_session)
    probation = probation_service.start_probation(db_session, standard_revision_id=rev, tenant_id=T1)
    probation_service.pause_probation(db_session, probation.id, T1)

    sid = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")], pad="pass").json()["submission_id"]
    resp = client.post(
        f"/api/qc/results/{sid}/final-decision",
        json={"tenant_id": T1, "decision": "pass", "decided_by": "qa1"},
    )
    assert resp.status_code == 201
    p = client.get(f"/api/qc/probation/{probation.id}", params={"tenant_id": T1}).json()
    assert p["status"] == "paused"
    assert p["gate"]["jobs_recorded"] == 0


def test_final_decision_resubmission_does_not_double_count_probation_job(client, db_session):
    """Amending and resubmitting the same submission's final decision must not
    inflate the probation job count -- record_probation_job's own job_ref
    de-dup is relied on, not re-derived here."""
    rev = _seed_revision(db_session)
    probation = probation_service.start_probation(db_session, standard_revision_id=rev, tenant_id=T1)
    sid = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")], pad="pass").json()["submission_id"]

    client.post(
        f"/api/qc/results/{sid}/final-decision",
        json={"tenant_id": T1, "decision": "pass", "decided_by": "qa1"},
    )
    resp2 = client.post(
        f"/api/qc/results/{sid}/final-decision",
        json={"tenant_id": T1, "decision": "reject", "decided_by": "qa2"},
    )
    assert resp2.status_code == 201  # amending the decision itself still succeeds
    p = client.get(f"/api/qc/probation/{probation.id}", params={"tenant_id": T1}).json()
    assert p["gate"]["jobs_recorded"] == 1


def test_final_decision_path_triggers_qualification_at_job_30(client, db_session):
    """WS7 §4: proves the agreement-rate check actually runs through the real
    HTTP result-submission flow at the specified cadence -- not just as a
    standalone probation.py unit test -- and that 90%+ agreement at job 30
    auto-transitions the standard to solo Active Inspection."""
    rev = _seed_revision(db_session)
    probation = probation_service.start_probation(db_session, standard_revision_id=rev, tenant_id=T1)

    for _ in range(30):
        sid = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")], pad="pass").json()["submission_id"]
        client.post(
            f"/api/qc/results/{sid}/final-decision",
            json={"tenant_id": T1, "decision": "pass", "decided_by": "qa1"},
        )

    p = client.get(f"/api/qc/probation/{probation.id}", params={"tenant_id": T1}).json()
    assert p["status"] == "qualified"
    assert p["gate"]["jobs_recorded"] == 30
    assert p["gate"]["qualified"] is True

    # Solo now -- further decisions must not attempt to record more probation
    # jobs (record_probation_job would raise ProbationNotActive if they did).
    sid2 = _submit(client, rev, [("cp1", "pass"), ("cp2", "pass")], pad="pass").json()["submission_id"]
    resp = client.post(
        f"/api/qc/results/{sid2}/final-decision",
        json={"tenant_id": T1, "decision": "pass", "decided_by": "qa1"},
    )
    assert resp.status_code == 201
    p2 = client.get(f"/api/qc/probation/{probation.id}", params={"tenant_id": T1}).json()
    assert p2["gate"]["jobs_recorded"] == 30  # unchanged -- standard now runs solo
