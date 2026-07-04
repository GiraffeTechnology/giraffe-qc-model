"""S3 — Bundle management tests (§7, §16.4).

Covers: bundle history/list/download; signature/checksum verification
fail-closed; tenant isolation.
"""
from __future__ import annotations

import copy

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_bundle_models  # noqa: F401
from src.api.deps import get_db_dep
from src.api.main import app
from src import config
from src.qc_model.bundle import manifest as m
from src.qc_model.bundle import service


T1 = "tenant_1"
T2 = "tenant_2"
SECRET = "test-secret"


@pytest.fixture()
def db_session(monkeypatch):
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


def _signed(tenant=T1, version="1.0.0"):
    return m.create_signed_bundle(
        bundle_version=version,
        tenant_id=tenant,
        skus=[{"sku_id": "sku1", "item_number": "SKU-1", "standard_revision_id": "rev1", "revision_no": 2}],
        photos=[{"photo_id": "p1", "sku_id": "sku1", "sha256": "a" * 64, "path": "photos/p1.jpg"}],
        created_by="studio@t1",
    )


# ── manifest / signing unit tests ─────────────────────────────────────────────


def test_manifest_counts_are_derived_not_trusted():
    signed = _signed()
    assert signed.manifest["sku_count"] == 1
    assert signed.manifest["standard_revision_count"] == 1


def test_verify_bundle_accepts_valid():
    signed = _signed()
    m.verify_bundle(signed)  # no raise


def test_verify_bundle_rejects_missing_signature():
    signed = _signed()
    signed.signature = ""
    with pytest.raises(m.BundleVerificationError) as exc:
        m.verify_bundle(signed)
    assert exc.value.reason == "missing_signature"


def test_verify_bundle_rejects_tampered_manifest():
    signed = _signed()
    signed.manifest["bundle_version"] = "9.9.9"  # signature no longer matches
    with pytest.raises(m.BundleVerificationError) as exc:
        m.verify_bundle(signed)
    # checksum recomputed from tampered manifest won't match stored sha256
    assert exc.value.reason in ("manifest_checksum_mismatch", "invalid_signature")


def test_verify_bundle_rejects_wrong_key():
    """A signature from a different Ed25519 key is rejected (fail-closed)."""
    from src.qc_model.bundle import ed25519 as ed

    signed = _signed()
    foreign_priv, _ = ed.generate_keypair_pem()
    foreign = ed.BundleSigner(ed._load_private_from_pem(foreign_priv))
    signed.signature = foreign.sign(m.canonical_json(signed.manifest).encode("utf-8"))
    with pytest.raises(m.BundleVerificationError) as exc:
        m.verify_bundle(signed)
    assert exc.value.reason == "invalid_signature"


def test_verify_bundle_rejects_photo_checksum_mismatch():
    signed = _signed()
    # sign over a manifest that declares one digest, present a different one
    m.verify_bundle(signed)  # baseline ok with no actual checksums
    with pytest.raises(m.BundleVerificationError) as exc:
        m.verify_bundle(signed, actual_photo_checksums={"p1": "b" * 64})
    assert exc.value.reason == "photo_checksum_mismatch"


def test_verify_bundle_rejects_missing_photo_checksum():
    signed = _signed()
    signed.manifest["photos"][0]["sha256"] = ""
    # re-sign so signature is valid but photo checksum is empty
    signed.signature = m.sign_manifest(signed.manifest)
    signed.manifest_sha256 = m.compute_manifest_sha256(signed.manifest)
    with pytest.raises(m.BundleVerificationError) as exc:
        m.verify_bundle(signed)
    assert exc.value.reason == "photo_checksum_missing"


def test_verify_bundle_rejects_forged_counts():
    signed = _signed()
    signed.manifest["sku_count"] = 99
    signed.signature = m.sign_manifest(signed.manifest)
    signed.manifest_sha256 = m.compute_manifest_sha256(signed.manifest)
    with pytest.raises(m.BundleVerificationError) as exc:
        m.verify_bundle(signed)
    assert exc.value.reason == "sku_count_mismatch"


# ── service / API tests ───────────────────────────────────────────────────────


def test_record_and_history_shows_bundle(client):
    signed = _signed(version="1.2.0")
    resp = client.post(
        "/api/qc/bundles",
        json={
            "tenant_id": T1,
            "manifest": signed.manifest,
            "signature": signed.signature,
            "signature_algo": signed.signature_algo,
            "manifest_sha256": signed.manifest_sha256,
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["bundle_version"] == "1.2.0"

    history = client.get("/api/qc/bundles", params={"tenant_id": T1}).json()
    assert len(history) == 1
    assert history[0]["sku_count"] == 1
    assert history[0]["signed"] is True


def test_download_returns_verified_manifest(client):
    signed = _signed(version="2.0.0")
    pk = client.post(
        "/api/qc/bundles",
        json={"tenant_id": T1, "manifest": signed.manifest, "signature": signed.signature},
    ).json()["id"]
    dl = client.get(f"/api/qc/bundles/{pk}/download", params={"tenant_id": T1})
    assert dl.status_code == 200
    body = dl.json()
    assert body["manifest"]["bundle_version"] == "2.0.0"
    assert body["signature"] == signed.signature


def test_record_rejects_bad_signature(client):
    signed = _signed()
    signed.signature = "deadbeef"
    resp = client.post(
        "/api/qc/bundles",
        json={"tenant_id": T1, "manifest": signed.manifest, "signature": signed.signature},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["reason"] == "invalid_signature"


def test_download_fails_closed_on_tampered_stored_manifest(client, db_session):
    signed = _signed(version="3.0.0")
    pk = client.post(
        "/api/qc/bundles",
        json={"tenant_id": T1, "manifest": signed.manifest, "signature": signed.signature},
    ).json()["id"]

    # Tamper with the stored row directly (simulate at-rest corruption).
    from src.db.qc_bundle_models import QCBundle

    row = db_session.get(QCBundle, pk)
    bad = copy.deepcopy(row.manifest_json)
    bad["bundle_version"] = "6.6.6"
    row.manifest_json = bad
    db_session.commit()

    dl = client.get(f"/api/qc/bundles/{pk}/download", params={"tenant_id": T1})
    assert dl.status_code == 409  # fail-closed, payload not served


def test_tenant_isolation(client):
    signed = _signed(tenant=T1, version="1.0.0")
    pk = client.post(
        "/api/qc/bundles",
        json={"tenant_id": T1, "manifest": signed.manifest, "signature": signed.signature},
    ).json()["id"]
    # T2 cannot see or download T1's bundle
    assert client.get("/api/qc/bundles", params={"tenant_id": T2}).json() == []
    assert client.get(f"/api/qc/bundles/{pk}", params={"tenant_id": T2}).status_code == 404
    assert client.get(f"/api/qc/bundles/{pk}/download", params={"tenant_id": T2}).status_code == 404


def test_record_rejects_tenant_mismatch(client):
    signed = _signed(tenant=T1)
    resp = client.post(
        "/api/qc/bundles",
        json={"tenant_id": T2, "manifest": signed.manifest, "signature": signed.signature},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["reason"] == "tenant_mismatch"


def test_admin_bundles_page_renders(client):
    signed = _signed(version="1.0.0")
    client.post(
        "/api/qc/bundles",
        json={"tenant_id": T1, "manifest": signed.manifest, "signature": signed.signature},
    )
    page = client.get("/admin/bundles", params={"tenant_id": T1})
    assert page.status_code == 200
    assert "1.0.0" in page.text
