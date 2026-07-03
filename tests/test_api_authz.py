"""Authentication + tenant-authorization tests for every external router group.

Unlike the functional tests, these exercise the REAL auth layer (signed bearer
tokens, no dependency override) and assert:

* anonymous access → 401 on every previously-open router group,
* a valid-but-wrong-tenant token accessing another tenant's resource → 404,
* the correct tenant token → 200.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
# Register every table with Base before create_all.
import src.db.qc_models  # noqa: F401
import src.db.sku_models  # noqa: F401
import src.db.intake_models  # noqa: F401
import src.db.execution_models  # noqa: F401
import src.db.pad_models  # noqa: F401
from src.api.main import app
from src.api.deps import get_db_dep
from src.api.auth import mint_token

TENANT_A = "tenant_a"
TENANT_B = "tenant_b"


def _bearer(tenant_id: str, is_admin: bool = False) -> dict:
    return {"Authorization": f"Bearer {mint_token(tenant_id, is_admin=is_admin)}"}


@pytest.fixture(scope="module")
def db_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    engine.dispose()


@pytest.fixture(scope="module")
def client(db_session_factory):
    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_dep] = override_get_db
    # NOTE: no auth override here — the genuine auth layer is under test.
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def tenant_a_data(client):
    """Build a full trained SKU for tenant A via the authenticated API."""
    hdr = _bearer(TENANT_A)

    sku = client.post(
        "/api/v1/sku",
        json={"item_number": "AUTHZ-001", "name": "Authz SKU"},
        headers=hdr,
    )
    assert sku.status_code == 201, sku.text
    sku_id = sku.json()["id"]

    std = client.post(
        "/api/v1/qc/standards",
        json={"tenant_id": TENANT_A, "sku_id": sku_id, "name": "Std"},
        headers=hdr,
    )
    assert std.status_code == 201, std.text
    standard_id = std.json()["id"]

    intake = client.post(
        "/api/v1/qc/intakes",
        json={"tenant_id": TENANT_A, "sku_id": sku_id, "raw_text": "Color must be red."},
        headers=hdr,
    )
    assert intake.status_code == 201, intake.text
    intake_id = intake.json()["id"]

    client.post(f"/api/v1/qc/intakes/{intake_id}/extract", headers=hdr)
    confirm = client.post(
        f"/api/v1/qc/intakes/{intake_id}/confirm",
        json={
            "tenant_id": TENANT_A,
            "confirmed_by": "eng1",
            "checkpoints": [
                {"point_code": "COLOR", "label": "Color", "severity": "major"}
            ],
        },
        headers=hdr,
    )
    assert confirm.status_code == 200, confirm.text

    job = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": TENANT_A, "sku_id": sku_id},
        headers=hdr,
    )
    assert job.status_code == 201, job.text
    job_id = job.json()["id"]

    return {
        "sku_id": sku_id,
        "standard_id": standard_id,
        "intake_id": intake_id,
        "job_id": job_id,
    }


# ── qc_router (standards) ───────────────────────────────────────────────────────


class TestQcRouterAuth:
    def test_anonymous_post_401(self, client):
        resp = client.post(
            "/api/v1/qc/standards",
            json={"tenant_id": TENANT_A, "sku_id": "x", "name": "n"},
        )
        assert resp.status_code == 401

    def test_anonymous_get_401(self, client, tenant_a_data):
        resp = client.get(f"/api/v1/qc/standards/{tenant_a_data['standard_id']}")
        assert resp.status_code == 401

    def test_correct_tenant_200(self, client, tenant_a_data):
        resp = client.get(
            f"/api/v1/qc/standards/{tenant_a_data['standard_id']}",
            headers=_bearer(TENANT_A),
        )
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == TENANT_A

    def test_wrong_tenant_404(self, client, tenant_a_data):
        resp = client.get(
            f"/api/v1/qc/standards/{tenant_a_data['standard_id']}",
            headers=_bearer(TENANT_B),
        )
        assert resp.status_code == 404

    def test_body_tenant_mismatch_403(self, client):
        # A token for tenant A but a body claiming tenant B → cross-tenant → 403.
        resp = client.post(
            "/api/v1/qc/standards",
            json={"tenant_id": TENANT_B, "sku_id": "x", "name": "n"},
            headers=_bearer(TENANT_A),
        )
        assert resp.status_code == 403


# ── sku_router ──────────────────────────────────────────────────────────────────


class TestSkuRouterAuth:
    def test_anonymous_search_401(self, client):
        assert client.get("/api/v1/sku/search", params={"q": "a"}).status_code == 401

    def test_anonymous_create_401(self, client):
        resp = client.post("/api/v1/sku", json={"item_number": "X", "name": "Y"})
        assert resp.status_code == 401

    def test_correct_tenant_200(self, client, tenant_a_data):
        resp = client.get(
            f"/api/v1/sku/{tenant_a_data['sku_id']}", headers=_bearer(TENANT_A)
        )
        assert resp.status_code == 200

    def test_wrong_tenant_404(self, client, tenant_a_data):
        resp = client.get(
            f"/api/v1/sku/{tenant_a_data['sku_id']}", headers=_bearer(TENANT_B)
        )
        assert resp.status_code == 404


# ── qc_intake_router ────────────────────────────────────────────────────────────


class TestIntakeRouterAuth:
    def test_anonymous_create_401(self, client):
        resp = client.post(
            "/api/v1/qc/intakes",
            json={"tenant_id": TENANT_A, "sku_id": "x", "raw_text": "t"},
        )
        assert resp.status_code == 401

    def test_anonymous_get_401(self, client, tenant_a_data):
        assert client.get(
            f"/api/v1/qc/intakes/{tenant_a_data['intake_id']}"
        ).status_code == 401

    def test_correct_tenant_200(self, client, tenant_a_data):
        resp = client.get(
            f"/api/v1/qc/intakes/{tenant_a_data['intake_id']}",
            headers=_bearer(TENANT_A),
        )
        assert resp.status_code == 200

    def test_wrong_tenant_404(self, client, tenant_a_data):
        resp = client.get(
            f"/api/v1/qc/intakes/{tenant_a_data['intake_id']}",
            headers=_bearer(TENANT_B),
        )
        assert resp.status_code == 404


# ── qc_inspection_router (job execution) ────────────────────────────────────────


class TestInspectionJobRouterAuth:
    def test_anonymous_create_401(self, client):
        resp = client.post(
            "/api/v1/qc/inspection-jobs",
            json={"tenant_id": TENANT_A, "sku_id": "x"},
        )
        assert resp.status_code == 401

    def test_anonymous_get_401(self, client, tenant_a_data):
        assert client.get(
            f"/api/v1/qc/inspection-jobs/{tenant_a_data['job_id']}"
        ).status_code == 401

    def test_correct_tenant_200(self, client, tenant_a_data):
        resp = client.get(
            f"/api/v1/qc/inspection-jobs/{tenant_a_data['job_id']}",
            headers=_bearer(TENANT_A),
        )
        assert resp.status_code == 200

    def test_wrong_tenant_404(self, client, tenant_a_data):
        resp = client.get(
            f"/api/v1/qc/inspection-jobs/{tenant_a_data['job_id']}",
            headers=_bearer(TENANT_B),
        )
        assert resp.status_code == 404


# ── sample_admin_router (admin group) ───────────────────────────────────────────


class TestAdminRouterAuth:
    def test_anonymous_post_401(self, client):
        resp = client.post(
            "/admin/samples",
            data={"item_number": "X", "name": "Y"},
            follow_redirects=False,
        )
        assert resp.status_code == 401

    def test_anonymous_get_redirects_to_login(self, client):
        resp = client.get("/admin/samples", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/admin/login"


# ── Token validation edge cases ─────────────────────────────────────────────────


class TestTokenValidation:
    def test_garbage_token_401(self, client):
        resp = client.get(
            "/api/v1/sku/search",
            params={"q": "a"},
            headers={"Authorization": "Bearer not-a-valid-token"},
        )
        assert resp.status_code == 401

    def test_non_bearer_scheme_401(self, client):
        resp = client.get(
            "/api/v1/sku/search",
            params={"q": "a"},
            headers={"Authorization": f"Basic {mint_token(TENANT_A)}"},
        )
        assert resp.status_code == 401
