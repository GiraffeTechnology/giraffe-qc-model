"""Upload-hardening tests (task A3): size cap, MIME whitelist, path traversal."""
from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_models  # noqa: F401
import src.db.sku_models  # noqa: F401
import src.db.pad_models  # noqa: F401
from src.api.main import app
from src.api.deps import get_db_dep
from src.api.uploads import validate_image_upload, validate_safe_id
from src.pad.session_service import _make_password_hash

TENANT = "default"
_PNG = (pathlib.Path(__file__).parent / "fixtures" / "red_square.png").read_bytes()


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
def admin_client(db_session_factory):
    def override_get_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_dep] = override_get_db

    from src.db.pad_models import QCOperatorProfile

    s = db_session_factory()
    try:
        s.add(
            QCOperatorProfile(
                tenant_id=TENANT,
                username="admin_up",
                display_name="Admin Upload",
                role="admin",
                preferred_language="en",
                password_hash=_make_password_hash("pw"),
                is_active=True,
            )
        )
        s.commit()
    finally:
        s.close()

    with TestClient(app, follow_redirects=True) as c:
        c.post(
            "/admin/login",
            data={"username": "admin_up", "password": "pw", "tenant_id": TENANT},
        )
        # Create a SKU to attach photos to.
        c.post("/admin/samples", data={"item_number": "UP-001", "name": "Upload SKU"})
        from src.db.sku_models import QCSkuItem

        s2 = db_session_factory()
        try:
            sku = (
                s2.query(QCSkuItem)
                .filter_by(tenant_id=TENANT, item_number="UP-001")
                .first()
            )
            c.sku_id = sku.id
        finally:
            s2.close()
        yield c
    app.dependency_overrides.clear()


# ── Unit-level helper tests ─────────────────────────────────────────────────────


class TestValidateHelpers:
    def test_valid_png_accepted(self):
        assert validate_image_upload(_PNG, "image/png") == "image/png"

    def test_oversized_rejected(self):
        with pytest.raises(Exception) as exc:
            validate_image_upload(b"\x89PNG\r\n\x1a\n" + b"0" * 100, "image/png", max_bytes=10)
        assert getattr(exc.value, "status_code", None) == 413

    def test_wrong_mime_rejected(self):
        with pytest.raises(Exception) as exc:
            validate_image_upload(b"%PDF-1.4 not an image", "application/pdf")
        assert getattr(exc.value, "status_code", None) == 415

    def test_disguised_text_rejected(self):
        # Declares image/png but the bytes are not a PNG → rejected.
        with pytest.raises(Exception) as exc:
            validate_image_upload(b"this is plain text, not an image", "image/png")
        assert getattr(exc.value, "status_code", None) == 415

    def test_safe_id_accepts_normal(self):
        assert validate_safe_id("abc-123_XYZ") == "abc-123_XYZ"

    @pytest.mark.parametrize("bad", ["../etc", "a/b", "..", "with space", "", "a" * 200])
    def test_safe_id_rejects_traversal(self, bad):
        with pytest.raises(Exception) as exc:
            validate_safe_id(bad, "sku_id")
        assert getattr(exc.value, "status_code", None) == 400


# ── End-to-end via the admin photo upload route ─────────────────────────────────


class TestAdminPhotoUpload:
    def test_valid_png_upload_ok(self, admin_client):
        resp = admin_client.post(
            f"/admin/samples/{admin_client.sku_id}/photos",
            files={"photo_file": ("s.png", _PNG, "image/png")},
            data={"is_primary": "true"},
        )
        assert resp.status_code == 200

    def test_wrong_mime_rejected(self, admin_client):
        resp = admin_client.post(
            f"/admin/samples/{admin_client.sku_id}/photos",
            files={"photo_file": ("s.pdf", b"%PDF-1.4 fake", "application/pdf")},
        )
        assert resp.status_code == 415

    def test_oversized_rejected(self, admin_client, monkeypatch):
        monkeypatch.setenv("MAX_UPLOAD_BYTES", "16")
        big = b"\x89PNG\r\n\x1a\n" + b"0" * 1000
        resp = admin_client.post(
            f"/admin/samples/{admin_client.sku_id}/photos",
            files={"photo_file": ("big.png", big, "image/png")},
        )
        assert resp.status_code == 413

    def test_traversal_sku_id_rejected(self, admin_client):
        # A traversal-style sku_id must be rejected before any filesystem use.
        resp = admin_client.post(
            "/admin/samples/..%2f..%2fetc/photos",
            files={"photo_file": ("s.png", _PNG, "image/png")},
            follow_redirects=False,
        )
        assert resp.status_code in (400, 404)


# ── End-to-end via the pad upload route ─────────────────────────────────────────


class TestPadUpload:
    def test_wrong_mime_rejected(self, admin_client, db_session_factory):
        # The pad upload requires an operator session; reuse a fresh client.
        from src.db.pad_models import QCOperatorProfile

        s = db_session_factory()
        try:
            if not s.query(QCOperatorProfile).filter_by(
                tenant_id="demo", username="op_up"
            ).first():
                s.add(
                    QCOperatorProfile(
                        tenant_id="demo",
                        username="op_up",
                        display_name="Op",
                        role="operator",
                        preferred_language="en",
                        password_hash=_make_password_hash("pw"),
                        is_active=True,
                    )
                )
                s.commit()
        finally:
            s.close()

        with TestClient(app, follow_redirects=True) as c:
            c.post(
                "/pad/login",
                data={"username": "op_up", "password": "pw", "tenant_id": "demo"},
            )
            resp = c.post(
                "/api/v1/pad/upload",
                files={"image": ("x.txt", b"not an image", "text/plain")},
            )
            assert resp.status_code == 415
