"""Auth gate + tenant-isolation tests for the production code path.

The rest of the suite runs on the test-only anonymous passthrough
(``APP_ENV=test`` + no credential). These tests instead exercise the enforced
path two ways:

* **rejection** — force ``APP_ENV=production`` so an anonymous request to a
  protected route is denied (401 / login redirect);
* **isolation** — present a real signed bearer token; the gate then runs in full
  even under ``APP_ENV=test``, so the effective tenant is pinned to the token's
  tenant regardless of any caller-supplied ``tenant_id``.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models          # noqa: F401
import src.db.execution_models    # noqa: F401
import src.db.intake_models       # noqa: F401
import src.db.studio_models       # noqa: F401
import src.db.qc_bundle_models    # noqa: F401
import src.db.qc_verdict_models   # noqa: F401
import src.db.pad_models          # noqa: F401
import src.db.qc_probation_models # noqa: F401
from src.db.qc_probation_models import QCProbation, QCProbationTransitionAudit

from src.api.main import app
from src.api.deps import get_db_dep
from src.api import auth
from src.api import startup


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    engine.dispose()


@pytest.fixture()
def client(db_factory):
    def override():
        s = db_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db_dep] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _admin_token(tenant: str) -> dict:
    return {"Authorization": f"Bearer {auth.mint_token(tenant, subject='a', is_admin=True)}"}


def _admin_actor_token(tenant: str, subject: str) -> dict:
    return {
        "Authorization": f"Bearer {auth.mint_token(tenant, subject=subject, is_admin=True)}"
    }


# ── Rejection (production) ────────────────────────────────────────────────────


def test_unauthenticated_api_is_401(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    r = client.get("/api/qc/bundles?tenant_id=t1")
    assert r.status_code == 401


def test_unauthenticated_admin_get_redirects_to_login(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    r = client.get("/admin/studio", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/admin/login")


def test_unauthenticated_detection_point_edit_is_rejected(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    r = client.patch(
        "/admin/studio/detection-points/not-known",
        json={"point_code": "DP-1", "label": "Changed"},
    )
    assert r.status_code == 401


def test_login_page_itself_is_public(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert client.get("/admin/login").status_code == 200


def test_non_admin_token_is_forbidden(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "strong-secret-for-token-signing")
    token = auth.mint_token("t1", subject="u", is_admin=False)
    r = client.get("/api/qc/bundles", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_probation_pause_persists_authenticated_actor(client, db_factory):
    db = db_factory()
    db.add(QCProbation(
        id="prob-audit-1",
        tenant_id="tenant_a",
        sku_id="sku-a",
        standard_revision_id="rev-a",
        status="active",
    ))
    db.commit()
    db.close()

    response = client.post(
        "/api/qc/probation/prob-audit-1/pause?tenant_id=tenant_b",
        headers=_admin_actor_token("tenant_a", "pad-admin-7"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paused"
    response = client.post(
        "/api/qc/probation/prob-audit-1/resume",
        headers=_admin_actor_token("tenant_a", "pad-admin-7"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"

    db = db_factory()
    audits = db.query(QCProbationTransitionAudit).all()
    assert {audit.action for audit in audits} == {"pause", "resume"}
    assert all(audit.tenant_id == "tenant_a" for audit in audits)
    assert all(audit.actor == "pad-admin-7" for audit in audits)
    by_action = {audit.action: audit for audit in audits}
    assert (by_action["pause"].previous_status, by_action["pause"].new_status) == (
        "active", "paused"
    )
    assert (by_action["resume"].previous_status, by_action["resume"].new_status) == (
        "paused", "active"
    )
    db.close()


# ── Isolation (real token, enforcement active) ────────────────────────────────


def test_bearer_token_pins_tenant_over_json_body(client):
    """A token for tenant_a creates a SKU even when the body says tenant_b."""
    r = client.post(
        "/admin/studio/chat",
        json={"tenant_id": "tenant_b", "message": "create sku FLW-001 Flower"},
        headers=_admin_token("tenant_a"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["action"] == "created_sku"

    # It lives under tenant_a, not tenant_b.
    a = client.get("/admin/studio/skus", headers=_admin_token("tenant_a")).json()["items"]
    assert any(i["item_number"] == "FLW-001" for i in a)
    b = client.get("/admin/studio/skus", headers=_admin_token("tenant_b")).json()["items"]
    assert not any(i["item_number"] == "FLW-001" for i in b)


def test_query_tenant_param_is_overridden_by_principal(client):
    """tenant_a token asking for ?tenant_id=tenant_b still gets tenant_a's data."""
    client.post(
        "/admin/studio/chat",
        json={"message": "create sku AAA-1 Widget"},
        headers=_admin_token("tenant_a"),
    )
    # Ask as tenant_a but try to widen to tenant_b via the query param.
    items = client.get(
        "/admin/studio/skus?tenant_id=tenant_b", headers=_admin_token("tenant_a")
    ).json()["items"]
    assert any(i["item_number"] == "AAA-1" for i in items)  # got tenant_a's, not tenant_b's


def test_cross_tenant_photo_not_readable(client):
    """A photo created under tenant_a is not served to a tenant_b principal."""
    created = client.post(
        "/admin/studio/chat",
        json={"message": "create sku PIC-1 Pic"},
        headers=_admin_token("tenant_a"),
    ).json()
    sku_id = created["sku"]["id"]
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id},
        files={"image": ("s.png", _png(), "image/png")},
        headers=_admin_token("tenant_a"),
    )
    assert up.status_code == 200, up.text
    url = up.json()["url"]  # carries ?tenant_id=tenant_a
    # tenant_a can read it.
    assert client.get(url, headers=_admin_token("tenant_a")).status_code == 200
    # tenant_b cannot — the gate rewrites the query tenant to tenant_b → 404.
    assert client.get(url, headers=_admin_token("tenant_b")).status_code == 404


def test_api_key_principal(client, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("QC_API_KEYS", '{"k-123": {"tenant_id": "t9", "admin": true}}')
    auth._static_api_keys_cache.cache_clear()
    r = client.get("/api/qc/bundles", headers={"X-API-Key": "k-123"})
    assert r.status_code == 200
    auth._static_api_keys_cache.cache_clear()


# ── v1 REST + qc-model surfaces are inside the auth gate ─────────────────────


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/sku/search?q=x&tenant_id=t1",
        "/api/v1/qc/intakes/some-id?tenant_id=t1",
        "/api/v1/qc/inspection-jobs/some-id?tenant_id=t1",
        "/api/qc-model/lifecycle?tenant_id=t1",
    ],
)
def test_unauthenticated_v1_api_is_401(client, monkeypatch, path):
    monkeypatch.setenv("APP_ENV", "production")
    r = client.get(path)
    assert r.status_code == 401


def test_v1_sku_create_pins_tenant_over_json_body(client):
    """A tenant_a token creates the SKU under tenant_a even if the body claims tenant_b."""
    r = client.post(
        "/api/v1/sku",
        json={"tenant_id": "tenant_b", "item_number": "V1-001", "name": "Widget"},
        headers=_admin_token("tenant_a"),
    )
    assert r.status_code == 201, r.text

    a = client.get("/api/v1/sku/search?q=V1-001", headers=_admin_token("tenant_a")).json()
    assert any(i["item_number"] == "V1-001" for i in a["items"])
    b = client.get("/api/v1/sku/search?q=V1-001", headers=_admin_token("tenant_b")).json()
    assert not any(i["item_number"] == "V1-001" for i in b["items"])


# ── SESSION_SECRET guard ──────────────────────────────────────────────────────


def test_session_secret_guard_rejects_default(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", auth.DEV_SESSION_SECRET_DEFAULT)
    with pytest.raises(RuntimeError):
        startup.validate_startup_config()
    with pytest.raises(RuntimeError):
        startup.session_secret()


def test_session_secret_guard_accepts_strong(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "a-strong-production-secret-value")
    startup.validate_startup_config()  # no raise
    assert startup.session_secret() == "a-strong-production-secret-value"


def _png() -> bytes:
    import struct
    import zlib

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(
            ">I", zlib.crc32(tag + data) & 0xFFFFFFFF
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
        + chunk(b"IEND", b"")
    )
