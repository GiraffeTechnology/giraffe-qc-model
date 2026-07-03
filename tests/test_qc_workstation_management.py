"""S3 — Workstation management tests (§6, §16.1, §16.4).

Covers: register/list; assign bundle (fail-closed verify); assigned vs installed
version; simulated Pad import/report path; tenant isolation.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_bundle_models  # noqa: F401
from src.api.deps import get_db_dep
from src.api.main import app
from src.qc_model.bundle import manifest as m


T1 = "tenant_1"
T2 = "tenant_2"
SECRET = "test-secret"


@pytest.fixture()
def db_session(monkeypatch):
    monkeypatch.setenv("BUNDLE_SIGNING_SECRET", SECRET)
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


def _record_bundle(client, tenant=T1, version="1.0.0"):
    signed = m.create_signed_bundle(
        bundle_version=version,
        tenant_id=tenant,
        skus=[{"sku_id": "s1", "item_number": "SKU-1", "standard_revision_id": "r1", "revision_no": 1}],
        photos=[{"photo_id": "p1", "sku_id": "s1", "sha256": "a" * 64, "path": "p1.jpg"}],
        secret=SECRET,
    )
    return client.post(
        "/api/qc/bundles",
        json={"tenant_id": tenant, "manifest": signed.manifest, "signature": signed.signature},
    ).json()["id"]


def _register(client, tenant=T1, wid="ws-1"):
    return client.post(
        "/api/qc/workstations",
        json={"tenant_id": tenant, "workstation_id": wid, "display_name": "Line 1", "site_or_line": "Site A"},
    ).json()


def test_register_workstation_has_exact_field_set(client):
    ws = _register(client)
    for field in (
        "workstation_id", "display_name", "site_or_line", "paired_status",
        "assigned_bundle_version", "installed_bundle_version", "last_seen_at",
        "last_sync_status", "last_error",
    ):
        assert field in ws
    assert ws["paired_status"] == "pending"
    assert ws["pairing_token"]  # pairing token / QR placeholder present


def test_register_is_idempotent_on_workstation_id(client):
    a = _register(client, wid="ws-dup")
    b = _register(client, wid="ws-dup")
    assert a["id"] == b["id"]
    assert len(client.get("/api/qc/workstations", params={"tenant_id": T1}).json()) == 1


def test_assign_bundle_sets_assigned_version(client):
    ws = _register(client)
    bundle_pk = _record_bundle(client, version="4.1.0")
    resp = client.post(
        f"/api/qc/workstations/{ws['id']}/assign",
        json={"tenant_id": T1, "bundle_pk": bundle_pk, "assigned_by": "admin"},
    )
    assert resp.status_code == 201
    assert resp.json()["assigned_bundle_version"] == "4.1.0"
    assert resp.json()["installed_bundle_version"] is None
    assert resp.json()["in_sync"] is False


def test_simulated_pad_report_updates_installed_and_sync(client):
    ws = _register(client)
    bundle_pk = _record_bundle(client, version="5.0.0")
    client.post(
        f"/api/qc/workstations/{ws['id']}/assign",
        json={"tenant_id": T1, "bundle_pk": bundle_pk},
    )
    # Pad imports the bundle and reports success.
    resp = client.post(
        f"/api/qc/workstations/{ws['id']}/report",
        json={
            "tenant_id": T1,
            "installed_bundle_version": "5.0.0",
            "sync_status": "ok",
            "outbox_upload_status": "flushed",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["installed_bundle_version"] == "5.0.0"
    assert body["last_sync_status"] == "ok"
    assert body["last_seen_at"] is not None
    assert body["in_sync"] is True
    assert body["last_error"] is None


def test_simulated_pad_report_records_import_error(client):
    ws = _register(client)
    resp = client.post(
        f"/api/qc/workstations/{ws['id']}/report",
        json={"tenant_id": T1, "sync_status": "import_failed", "error": "signature_invalid"},
    )
    assert resp.status_code == 200
    assert resp.json()["last_sync_status"] == "import_failed"
    assert resp.json()["last_error"] == "signature_invalid"


def test_assign_unknown_bundle_404(client):
    ws = _register(client)
    resp = client.post(
        f"/api/qc/workstations/{ws['id']}/assign",
        json={"tenant_id": T1, "bundle_pk": "nope"},
    )
    assert resp.status_code == 404


def test_tenant_isolation_on_report(client):
    ws = _register(client, tenant=T1)
    resp = client.post(
        f"/api/qc/workstations/{ws['id']}/report",
        json={"tenant_id": T2, "sync_status": "ok"},
    )
    assert resp.status_code == 404


def test_admin_workstations_page_renders(client):
    _register(client)
    page = client.get("/admin/workstations", params={"tenant_id": T1})
    assert page.status_code == 200
    assert "Line 1" in page.text
