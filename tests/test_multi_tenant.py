"""Multi-tenant isolation tests.

Tenant A cannot read Tenant B's data.
Returns 404 (not 403 to avoid leaking existence).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
from src.db.qc_models import (  # noqa: F401 — registers new tables
    CapturePhoto,
    InspectionRun,
    ProductStandard,
    QCAsset,
    QCPoint,
    StandardPhoto,
)
import src.db.sku_models  # noqa: F401
import src.db.execution_models  # noqa: F401
from src.api.main import app
from src.api.deps import get_db_dep
from src.db.seed_data import seed_flower_brooch


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def db_session_factory(db_engine):
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
def client(db_session_factory):
    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_dep] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


TENANT_A = "tenant_alpha"
TENANT_B = "tenant_beta"
SKU = "SKU-MULTI-TENANT"


class TestProductStandardTenantIsolation:
    @pytest.fixture(autouse=True)
    def setup_standards(self, client):
        # Create standard for Tenant A
        resp_a = client.post("/api/v1/qc/standards", json={
            "tenant_id": TENANT_A,
            "sku_id": SKU,
            "name": "Tenant A Standard",
        })
        self.standard_a_id = resp_a.json()["id"]

        # Create standard for Tenant B
        resp_b = client.post("/api/v1/qc/standards", json={
            "tenant_id": TENANT_B,
            "sku_id": SKU,
            "name": "Tenant B Standard",
        })
        self.standard_b_id = resp_b.json()["id"]

    def test_tenant_a_can_read_own_standard(self, client):
        resp = client.get(
            f"/api/v1/qc/standards/{self.standard_a_id}",
            params={"tenant_id": TENANT_A}
        )
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == TENANT_A

    def test_tenant_b_cannot_read_tenant_a_standard(self, client):
        """Tenant B requesting Tenant A's standard ID should get 404, not 403."""
        resp = client.get(
            f"/api/v1/qc/standards/{self.standard_a_id}",
            params={"tenant_id": TENANT_B}
        )
        assert resp.status_code == 404

    def test_tenant_a_cannot_read_tenant_b_standard(self, client):
        resp = client.get(
            f"/api/v1/qc/standards/{self.standard_b_id}",
            params={"tenant_id": TENANT_A}
        )
        assert resp.status_code == 404

    def test_404_not_403(self, client):
        """Verify the isolation returns 404, not 403 (don't leak existence)."""
        resp = client.get(
            f"/api/v1/qc/standards/{self.standard_a_id}",
            params={"tenant_id": TENANT_B}
        )
        assert resp.status_code == 404
        # Must NOT be 403 (that would leak existence of the resource)
        assert resp.status_code != 403

    def test_by_sku_does_not_leak_cross_tenant(self, client):
        """by-sku listing should only return standards for the requesting tenant."""
        resp_a = client.get(
            f"/api/v1/qc/standards/by-sku/{SKU}",
            params={"tenant_id": TENANT_A}
        )
        assert resp_a.status_code == 200
        results = resp_a.json()
        # All results must belong to Tenant A
        for std in results:
            assert std["tenant_id"] == TENANT_A

    def test_tenant_b_by_sku_does_not_include_tenant_a(self, client):
        resp_b = client.get(
            f"/api/v1/qc/standards/by-sku/{SKU}",
            params={"tenant_id": TENANT_B}
        )
        assert resp_b.status_code == 200
        results = resp_b.json()
        for std in results:
            assert std["tenant_id"] == TENANT_B


class TestCaptureTenantIsolation:
    @pytest.fixture(autouse=True)
    def setup_captures(self, client, tmp_path):
        img_a = tmp_path / "capture_a.jpg"
        img_a.write_bytes(b"\x00" * 50)
        resp_a = client.post("/api/v1/qc/captures", json={
            "tenant_id": TENANT_A,
            "sku_id": SKU,
            "local_path": str(img_a),
        })
        self.capture_a_id = resp_a.json()["id"]

        img_b = tmp_path / "capture_b.jpg"
        img_b.write_bytes(b"\x00" * 50)
        resp_b = client.post("/api/v1/qc/captures", json={
            "tenant_id": TENANT_B,
            "sku_id": SKU,
            "local_path": str(img_b),
        })
        self.capture_b_id = resp_b.json()["id"]

    def test_tenant_a_can_read_own_capture(self, client):
        resp = client.get(
            f"/api/v1/qc/captures/{self.capture_a_id}",
            params={"tenant_id": TENANT_A}
        )
        assert resp.status_code == 200

    def test_tenant_b_cannot_read_tenant_a_capture(self, client):
        resp = client.get(
            f"/api/v1/qc/captures/{self.capture_a_id}",
            params={"tenant_id": TENANT_B}
        )
        assert resp.status_code == 404

    def test_cross_tenant_capture_returns_404_not_403(self, client):
        resp = client.get(
            f"/api/v1/qc/captures/{self.capture_b_id}",
            params={"tenant_id": TENANT_A}
        )
        assert resp.status_code == 404
        assert resp.status_code != 403


class TestInspectionTenantIsolation:
    @pytest.fixture(autouse=True)
    def setup_inspections(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")

        # Setup for Tenant A
        std_resp = client.post("/api/v1/qc/standards", json={
            "tenant_id": TENANT_A,
            "sku_id": SKU,
            "name": "Tenant A Inspection Standard",
        })
        self.standard_a_id = std_resp.json()["id"]

        client.post(f"/api/v1/qc/standards/{self.standard_a_id}/qc-points", json={
            "tenant_id": TENANT_A,
            "qc_point_code": "ISOLATION_QCP",
            "name": "Isolation Test Point",
            "description": "Test",
        })

        img = tmp_path / "mt_capture.jpg"
        img.write_bytes(b"\x00" * 50)
        cap_resp = client.post("/api/v1/qc/captures", json={
            "tenant_id": TENANT_A,
            "sku_id": SKU,
            "local_path": str(img),
        })
        self.capture_a_id = cap_resp.json()["id"]

        run_resp = client.post("/api/v1/qc/inspect", json={
            "tenant_id": TENANT_A,
            "sku_id": SKU,
            "standard_id": self.standard_a_id,
            "capture_photo_id": self.capture_a_id,
        })
        self.inspection_a_id = run_resp.json()["inspection_run"]["id"]

    def test_tenant_a_can_read_own_inspection(self, client):
        resp = client.get(
            f"/api/v1/qc/inspections/{self.inspection_a_id}",
            params={"tenant_id": TENANT_A}
        )
        assert resp.status_code == 200

    def test_tenant_b_cannot_read_tenant_a_inspection(self, client):
        resp = client.get(
            f"/api/v1/qc/inspections/{self.inspection_a_id}",
            params={"tenant_id": TENANT_B}
        )
        assert resp.status_code == 404

    def test_tenant_b_cannot_read_tenant_a_inspection_result(self, client):
        resp = client.get(
            f"/api/v1/qc/inspections/{self.inspection_a_id}/results",
            params={"tenant_id": TENANT_B}
        )
        assert resp.status_code == 404


class TestInspectionJobTenantIsolation:
    @pytest.fixture(autouse=True)
    def setup_job(self, client, db_session_factory):
        session = db_session_factory()
        try:
            sku = seed_flower_brooch(session, tenant_id=TENANT_A)
            self.sku_id = sku.id
        finally:
            session.close()

        job_resp = client.post(
            "/api/v1/qc/inspection-jobs",
            json={"tenant_id": TENANT_A, "sku_id": self.sku_id, "job_ref": "TENANT-A-JOB"},
        )
        assert job_resp.status_code == 201, job_resp.text
        self.job_id = job_resp.json()["id"]

    def test_get_job_cross_tenant_returns_404(self, client):
        resp = client.get(
            f"/api/v1/qc/inspection-jobs/{self.job_id}",
            params={"tenant_id": TENANT_B},
        )
        assert resp.status_code == 404

    def test_add_media_cross_tenant_returns_404(self, client):
        resp = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/media",
            json={"tenant_id": TENANT_B, "image_url": "http://example.invalid/capture.jpg"},
        )
        assert resp.status_code == 404

    def test_model_results_cross_tenant_returns_404(self, client):
        resp = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/model-results",
            json={
                "tenant_id": TENANT_B,
                "provider": "test",
                "model_name": "test-model",
                "raw_output": {"checkpoint_results": [], "incidental_findings": []},
            },
        )
        assert resp.status_code == 404

    def test_checkpoint_results_cross_tenant_returns_404(self, client):
        resp = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/checkpoint-results",
            json={"tenant_id": TENANT_B, "detection_point_id": "does-not-matter", "result": "pass"},
        )
        assert resp.status_code == 404

    def test_incidental_findings_cross_tenant_returns_404(self, client):
        resp = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/incidental-findings",
            json={"tenant_id": TENANT_B, "description": "cross-tenant probe", "severity": "minor"},
        )
        assert resp.status_code == 404

    def test_finalize_cross_tenant_returns_404(self, client):
        resp = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/finalize",
            json={"tenant_id": TENANT_B},
        )
        assert resp.status_code == 404

    def test_report_cross_tenant_returns_404(self, client):
        resp = client.get(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/report",
            params={"tenant_id": TENANT_B},
        )
        assert resp.status_code == 404

    def test_create_job_missing_tenant_id_returns_422(self, client):
        resp = client.post(
            "/api/v1/qc/inspection-jobs",
            json={"sku_id": self.sku_id, "job_ref": "MISSING-TENANT"},
        )
        assert resp.status_code == 422
