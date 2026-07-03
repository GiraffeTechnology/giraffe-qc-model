"""Tests for the QC FastAPI endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
from src.db.qc_models import (  # noqa: F401 — registers new tables with Base.metadata
    CapturePhoto,
    InspectionRun,
    ProductStandard,
    QCAsset,
    QCPoint,
    StandardPhoto,
)
from src.api.main import app
from src.api.deps import get_db_dep
from tests._auth_override import install_api_auth_override


# ─── Fixtures ─────────────────────────────────────────────────────────────────


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
    install_api_auth_override(app)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


TENANT = "tenant_test"
SKU = "SKU-API-TEST"


# ─── Standard Tests ───────────────────────────────────────────────────────────


class TestCreateStandard:
    def test_create_standard_success(self, client):
        resp = client.post("/api/v1/qc/standards", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "name": "Test Standard",
            "version": "1.0",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["tenant_id"] == TENANT
        assert data["sku_id"] == SKU
        assert data["name"] == "Test Standard"
        assert "id" in data

    def test_create_standard_returns_id(self, client):
        resp = client.post("/api/v1/qc/standards", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "name": "Another Standard",
        })
        assert resp.status_code == 201
        assert len(resp.json()["id"]) > 0


# ─── QC Point Tests ───────────────────────────────────────────────────────────


class TestCreateQCPoint:
    @pytest.fixture(autouse=True)
    def create_standard(self, client):
        resp = client.post("/api/v1/qc/standards", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "name": "QCP Test Standard",
        })
        self.standard_id = resp.json()["id"]

    def test_create_qc_point_success(self, client):
        resp = client.post(f"/api/v1/qc/standards/{self.standard_id}/qc-points", json={
            "tenant_id": TENANT,
            "qc_point_code": "COLOR_001",
            "name": "Color Check",
            "description": "Check color matches standard",
            "severity": "critical",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["qc_point_code"] == "COLOR_001"
        assert data["name"] == "Color Check"
        assert data["standard_id"] == self.standard_id

    def test_create_qc_point_unknown_standard_returns_404(self, client):
        resp = client.post("/api/v1/qc/standards/NONEXISTENT_ID/qc-points", json={
            "tenant_id": TENANT,
            "qc_point_code": "TEST",
            "name": "Test",
            "description": "Test",
        })
        assert resp.status_code == 404


# ─── Capture Tests ────────────────────────────────────────────────────────────


class TestPostCapture:
    def test_create_capture_success(self, client, tmp_path):
        # Create a dummy capture image
        img = tmp_path / "capture.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 50)

        resp = client.post("/api/v1/qc/captures", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "local_path": str(img),
            "capture_source": "manual",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["tenant_id"] == TENANT
        assert data["sku_id"] == SKU
        assert "id" in data

    def test_get_capture_success(self, client, tmp_path):
        img = tmp_path / "get_capture.jpg"
        img.write_bytes(b"\x00" * 50)

        create_resp = client.post("/api/v1/qc/captures", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "local_path": str(img),
        })
        capture_id = create_resp.json()["id"]

        get_resp = client.get(f"/api/v1/qc/captures/{capture_id}", params={"tenant_id": TENANT})
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == capture_id


# ─── Inspection Tests ─────────────────────────────────────────────────────────


class TestRunInspection:
    @pytest.fixture(autouse=True)
    def setup(self, client, tmp_path, monkeypatch):
        # Ensure cloud is disabled so FakeCloudQwenProvider is used
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")

        # Create standard
        std_resp = client.post("/api/v1/qc/standards", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "name": "Inspection Test Standard",
        })
        self.standard_id = std_resp.json()["id"]

        # Create QC point
        qcp_resp = client.post(f"/api/v1/qc/standards/{self.standard_id}/qc-points", json={
            "tenant_id": TENANT,
            "qc_point_code": "VISUAL_001",
            "name": "Visual Check",
            "description": "Check visual appearance",
        })
        self.qc_point_id = qcp_resp.json()["id"]

        # Create capture
        img = tmp_path / "insp_capture.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        cap_resp = client.post("/api/v1/qc/captures", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "local_path": str(img),
        })
        self.capture_id = cap_resp.json()["id"]

    def test_run_inspection_success(self, client):
        resp = client.post("/api/v1/qc/inspect", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "standard_id": self.standard_id,
            "capture_photo_id": self.capture_id,
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "inspection_run" in data
        assert "result" in data
        assert "event" in data
        assert data["result"]["overall_result"] in ("pass", "fail", "review_required")

    def test_inspection_result_has_items(self, client):
        resp = client.post("/api/v1/qc/inspect", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "standard_id": self.standard_id,
            "capture_photo_id": self.capture_id,
        })
        assert resp.status_code == 201
        items = resp.json()["result"]["items"]
        assert len(items) >= 1

    def test_query_inspection_result(self, client):
        # Run inspection
        run_resp = client.post("/api/v1/qc/inspect", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "standard_id": self.standard_id,
            "capture_photo_id": self.capture_id,
        })
        inspection_id = run_resp.json()["inspection_run"]["id"]

        # Query result
        result_resp = client.get(
            f"/api/v1/qc/inspections/{inspection_id}/results",
            params={"tenant_id": TENANT}
        )
        assert result_resp.status_code == 200
        data = result_resp.json()
        assert data["inspection_run_id"] == inspection_id
        assert data["overall_result"] in ("pass", "fail", "review_required")

    def test_query_inspection_run(self, client):
        run_resp = client.post("/api/v1/qc/inspect", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "standard_id": self.standard_id,
            "capture_photo_id": self.capture_id,
        })
        inspection_id = run_resp.json()["inspection_run"]["id"]

        get_resp = client.get(
            f"/api/v1/qc/inspections/{inspection_id}",
            params={"tenant_id": TENANT}
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == inspection_id
        assert get_resp.json()["status"] == "done"


# ─── Asset Tests ──────────────────────────────────────────────────────────────


class TestQueryAsset:
    @pytest.fixture(autouse=True)
    def setup(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")

        std_resp = client.post("/api/v1/qc/standards", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "name": "Asset Test Standard",
        })
        self.standard_id = std_resp.json()["id"]

        # Add QC point
        client.post(f"/api/v1/qc/standards/{self.standard_id}/qc-points", json={
            "tenant_id": TENANT,
            "qc_point_code": "ASSET_QCP",
            "name": "Asset QC Point",
            "description": "For asset tests",
        })

        img = tmp_path / "asset_capture.jpg"
        img.write_bytes(b"\xff\xd8\xff" + b"\x00" * 100)
        cap_resp = client.post("/api/v1/qc/captures", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "local_path": str(img),
        })
        self.capture_id = cap_resp.json()["id"]

        run_resp = client.post("/api/v1/qc/inspect", json={
            "tenant_id": TENANT,
            "sku_id": SKU,
            "standard_id": self.standard_id,
            "capture_photo_id": self.capture_id,
        })
        self.inspection_id = run_resp.json()["inspection_run"]["id"]

    def test_get_assets_by_inspection(self, client):
        resp = client.get(
            f"/api/v1/qc/assets/by-inspection/{self.inspection_id}",
            params={"tenant_id": TENANT}
        )
        assert resp.status_code == 200
        assets = resp.json()
        assert len(assets) >= 1

    def test_get_asset_by_id(self, client):
        assets_resp = client.get(
            f"/api/v1/qc/assets/by-inspection/{self.inspection_id}",
            params={"tenant_id": TENANT}
        )
        asset_id = assets_resp.json()[0]["id"]

        get_resp = client.get(
            f"/api/v1/qc/assets/{asset_id}",
            params={"tenant_id": TENANT}
        )
        assert get_resp.status_code == 200
        assert get_resp.json()["id"] == asset_id

    def test_asset_contains_pii_defaults_false(self, client):
        assets_resp = client.get(
            f"/api/v1/qc/assets/by-inspection/{self.inspection_id}",
            params={"tenant_id": TENANT}
        )
        for asset in assets_resp.json():
            assert asset["contains_pii"] is False
