"""PR15 Pad QC E2E v1 tests."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.deps import get_db_dep
from src.api.main import app
from src.db.models import Base
import src.db.execution_models  # noqa: F401
import src.db.intake_models  # noqa: F401
import src.db.models  # noqa: F401
import src.db.pad_models  # noqa: F401
import src.db.qc_models  # noqa: F401
import src.db.sku_models  # noqa: F401
from src.pad.session_service import seed_demo_operators


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    seed_demo_operators(session, tenant_id="demo")
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    def override_db():
        yield db_session

    app.dependency_overrides[get_db_dep] = override_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def auth_client(client):
    resp = client.post(
        "/pad/login",
        data={"username": "operator_cn", "password": "operator_cn", "tenant_id": "demo"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 200)
    return client


@pytest.fixture()
def seeded_sku(db_session):
    from src.db.seed_data import seed_shirt_custom

    return seed_shirt_custom(db_session, tenant_id="demo")


def test_pad_sku_selector_search_returns_seeded_sku(auth_client, seeded_sku):
    resp = auth_client.get("/api/v1/pad/skus?q=SHIRT")
    assert resp.status_code == 200
    ids = {sku["id"] for sku in resp.json()["skus"]}
    assert seeded_sku.id in ids


def test_pad_qc_e2e_active_standard_to_report_pass_flow(auth_client, seeded_sku):
    job_resp = auth_client.post(
        "/api/v1/pad/create_inspection_job",
        json={"sku_id": seeded_sku.id, "job_ref": "PAD-E2E-001"},
    )
    assert job_resp.status_code == 200
    job_data = job_resp.json()
    assert job_data["status"] == "job_created"
    job_id = job_data["job_id"]
    assert job_data["active_standard_revision_id"]

    media_resp = auth_client.post(
        f"/api/v1/pad/inspections/{job_id}/media",
        files={"image": ("shirt-front.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert media_resp.status_code == 201
    media_data = media_resp.json()
    assert media_data["status"] == "media_attached"
    assert media_data["job_id"] == job_id
    assert media_data["media_id"]
    assert re.fullmatch(r"[0-9a-f]{64}", media_data["sha256"])

    run_resp = auth_client.post(
        f"/api/v1/pad/inspections/{job_id}/run_model",
        json={"media_id": media_data["media_id"]},
    )
    assert run_resp.status_code == 201
    run_data = run_resp.json()
    assert run_data["status"] == "model_output_ingested"
    assert run_data["model_result_id"]
    assert len(run_data["checkpoint_results"]) >= 4
    assert {row["result"] for row in run_data["checkpoint_results"]} == {"pass"}

    finalize_resp = auth_client.post(f"/api/v1/pad/inspections/{job_id}/finalize")
    assert finalize_resp.status_code == 200
    finalize_data = finalize_resp.json()
    assert finalize_data["status"] == "finalized"
    assert finalize_data["overall_result"] == "pass"
    assert finalize_data["checkpoint_results_count"] == len(run_data["checkpoint_results"])

    report_resp = auth_client.get(f"/api/v1/pad/inspections/{job_id}/report")
    assert report_resp.status_code == 200
    report_data = report_resp.json()
    assert report_data["job"]["id"] == job_id
    assert report_data["report"]["overall_result"] == "pass"
    assert len(report_data["checkpoint_results"]) == len(run_data["checkpoint_results"])
    assert report_data["audit"]["tenant_id"] == "demo"


def test_pad_qc_e2e_force_fail_routes_to_fail_verdict(auth_client, seeded_sku):
    job_resp = auth_client.post(
        "/api/v1/pad/create_inspection_job",
        json={"sku_id": seeded_sku.id, "job_ref": "PAD-E2E-FAIL"},
    )
    assert job_resp.status_code == 200
    job_id = job_resp.json()["job_id"]

    run_resp = auth_client.post(
        f"/api/v1/pad/inspections/{job_id}/run_model",
        json={"force_fail_point_code": "BUTTON_COUNT"},
    )
    assert run_resp.status_code == 201
    results = run_resp.json()["checkpoint_results"]
    assert any(row["point_code"] == "BUTTON_COUNT" and row["result"] == "fail" for row in results)

    finalize_resp = auth_client.post(f"/api/v1/pad/inspections/{job_id}/finalize")
    assert finalize_resp.status_code == 200
    assert finalize_resp.json()["overall_result"] == "fail"
