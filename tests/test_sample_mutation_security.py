"""P0 sample mutation and publication re-authorization rules."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.deps import get_db_dep
from src.api.main import app
from src.db.models import Base
import src.db.execution_models  # noqa: F401
import src.db.intake_models  # noqa: F401
import src.db.pad_models  # noqa: F401
import src.db.sku_models  # noqa: F401
import src.db.studio_models  # noqa: F401
import src.db.training_models  # noqa: F401
from src.db.pad_models import QCOperatorProfile
from src.pad.session_service import _make_password_hash

MUTATION_KEY = "separate-sample-mutation-key"
SURFACE_HEADERS = {
    "X-QC-Mutation-Key": MUTATION_KEY,
    "X-QC-Sample-Surface": "sample-standard",
}


def _client(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("QC_SAMPLE_MUTATION_KEY", MUTATION_KEY)
    monkeypatch.delenv("QC_SAMPLE_MUTATION_KEY_HASH", raising=False)
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_dep] = override_db
    return TestClient(app), session_factory, engine


def _sample_payload(item_number="SEC-001"):
    return {
        "tenant_id": "default",
        "item_number": item_number,
        "name": "Secured sample",
    }


def test_sample_mutation_requires_valid_second_credential(monkeypatch):
    client, _, engine = _client(monkeypatch)
    try:
        assert client.post("/admin/samples", data=_sample_payload()).status_code == 403
        assert client.post(
            "/admin/samples",
            data=_sample_payload(),
            headers={"X-QC-Mutation-Key": "wrong-mutation-key"},
        ).status_code == 403
        accepted = client.post(
            "/admin/samples",
            data=_sample_payload(),
            headers=SURFACE_HEADERS,
            follow_redirects=False,
        )
        assert accepted.status_code == 303
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_sample_authoring_api_requires_sample_standard_surface(monkeypatch):
    client, _, engine = _client(monkeypatch)
    try:
        missing_surface = client.post(
            "/admin/studio/chat",
            json={"tenant_id": "default", "message": "create sku SEC-002"},
            headers={"X-QC-Mutation-Key": MUTATION_KEY},
        )
        assert missing_surface.status_code == 403
        accepted = client.post(
            "/admin/studio/chat",
            json={"tenant_id": "default", "message": "create sku SEC-002"},
            headers=SURFACE_HEADERS,
        )
        assert accepted.status_code == 200
        assert accepted.json()["sku"]["item_number"] == "SEC-002"
        assert client.post(
            "/admin/studio/upload",
            data={"sku_id": accepted.json()["sku"]["id"]},
            files={"image": ("x.png", b"not-used", "image/png")},
            headers=SURFACE_HEADERS,
        ).status_code == 404
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_sample_photo_acquisition_requires_usb_camera_source(monkeypatch):
    client, _, engine = _client(monkeypatch)
    try:
        created = client.post(
            "/admin/studio/chat",
            json={"tenant_id": "default", "message": "create sku SEC-USB-001"},
            headers=SURFACE_HEADERS,
        )
        sku_id = created.json()["sku"]["id"]
        denied_file = client.post(
            f"/admin/samples/{sku_id}/photos",
            data={"tenant_id": "default", "capture_source": "file_upload"},
            files={"photo_file": ("x.png", b"not-an-image", "image/png")},
            headers=SURFACE_HEADERS,
        )
        assert denied_file.status_code == 403
        denied_url = client.post(
            f"/admin/samples/{sku_id}/photos",
            data={"tenant_id": "default", "capture_source": "usb_camera",
                  "image_url": "https://example.invalid/sample.png"},
            headers=SURFACE_HEADERS,
        )
        assert denied_url.status_code == 403
        denied_legacy_upload = client.post(
            "/admin/samples/upload",
            data={"tenant_id": "default", "sku_id": sku_id},
            files={"image": ("x.png", b"not-an-image", "image/png")},
            headers=SURFACE_HEADERS,
        )
        assert denied_legacy_upload.status_code == 403
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_formal_publish_requires_second_credential_before_business_checks(monkeypatch):
    client, _, engine = _client(monkeypatch)
    try:
        denied = client.post(
            "/admin/studio/publish",
            json={"tenant_id": "default", "sku_id": "missing"},
        )
        assert denied.status_code == 403
        authorized = client.post(
            "/admin/studio/publish",
            json={"tenant_id": "default", "sku_id": "missing"},
            headers={"X-QC-Mutation-Key": MUTATION_KEY},
        )
        assert authorized.status_code == 400
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_mutation_credential_cannot_equal_login_password(monkeypatch):
    shared = "same-login-and-mutation-secret"
    client, session_factory, engine = _client(monkeypatch)
    monkeypatch.setenv("QC_SAMPLE_MUTATION_KEY", shared)
    session = session_factory()
    session.add(QCOperatorProfile(
        tenant_id="demo",
        username="security_admin",
        display_name="Security Admin",
        role="admin",
        preferred_language="zh-CN",
        password_hash=_make_password_hash(shared),
        is_active=True,
    ))
    session.commit()
    session.close()
    try:
        login = client.post(
            "/admin/login",
            data={"username": "security_admin", "password": shared, "tenant_id": "demo"},
            follow_redirects=False,
        )
        assert login.status_code == 303
        rejected = client.post(
            "/admin/samples",
            data={"tenant_id": "demo", "item_number": "SEC-003", "name": "Separated"},
            headers={"X-QC-Mutation-Key": shared},
        )
        assert rejected.status_code == 400
        assert "must differ" in rejected.json()["detail"]
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()
