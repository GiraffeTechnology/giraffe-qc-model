"""P0 sample mutation and publication re-authorization rules.

Workflow (2026-07-23 correction): entry (creating a sample) and any
authoring/edits before a sample is first published need no extra credential.
Once a sample has been published at least once, every further operation on
it -- and every publish, including the first one -- requires a second
credential distinct from the login password/API key.
"""
from __future__ import annotations

import struct
import zlib
from datetime import datetime, timedelta, timezone

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
from src.db.training_models import QCTrainingJudgment
from src.pad.session_service import _make_password_hash

MUTATION_KEY = "separate-sample-mutation-key"
SURFACE_HEADERS = {"X-QC-Sample-Surface": "sample-standard"}
AUTHORIZED_HEADERS = dict(SURFACE_HEADERS, **{"X-QC-Mutation-Key": MUTATION_KEY})


def _tiny_png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


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
    return {"tenant_id": "default", "item_number": item_number, "name": "Secured sample"}


def _create_confirm_and_upload(client, item_number: str) -> tuple[str, str]:
    """Entry + confirmation + photo upload, all pre-publish (no credential)."""
    created = client.post(
        "/admin/samples", data=_sample_payload(item_number), follow_redirects=False
    )
    assert created.status_code == 303, created.text
    sku_id = created.headers["location"].split("/")[-1].split("?")[0]

    card = client.post(
        "/admin/studio/chat",
        json={"message": "stamen centering", "sku_id": sku_id},
        headers=SURFACE_HEADERS,
    ).json()["confirmation_card"]
    confirmed = client.post(
        "/admin/studio/confirm",
        json={"intake_id": card["intake_id"], "checkpoints": card["checkpoints"]},
        headers=SURFACE_HEADERS,
    )
    assert confirmed.status_code == 200, confirmed.text

    uploaded = client.post(
        "/admin/samples/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
        headers=SURFACE_HEADERS,
    )
    assert uploaded.status_code == 200, uploaded.text
    return sku_id, confirmed.json()["revision_id"]


def _qualify_and_publish(client, session_factory, sku_id: str, revision_id: str) -> None:
    session = session_factory()
    try:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(30):
            session.add(QCTrainingJudgment(
                id=f"jdg-{sku_id}-{i}", tenant_id="default", sku_id=sku_id,
                standard_revision_id=revision_id,
                ground_truth_label="qualified" if i % 2 == 0 else "unqualified",
                model_overall_result="pass" if i % 2 == 0 else "fail",
                model_checkpoint_results_json=[],
                status="reviewed", admin_decision="correct", admin_id="test-admin",
                reviewed_at=base + timedelta(seconds=i),
                is_false_pass=False,
                created_at=base + timedelta(seconds=i),
            ))
        session.commit()
    finally:
        session.close()
    published = client.post(
        "/admin/studio/publish",
        json={"tenant_id": "default", "sku_id": sku_id},
        headers=AUTHORIZED_HEADERS,
    )
    assert published.status_code == 200, published.text


def test_sample_creation_and_pre_publish_authoring_need_no_credential(monkeypatch):
    """Entry (create) and pre-publish edits succeed with no mutation credential
    at all -- only the Sample & Standard surface header is required."""
    client, _, engine = _client(monkeypatch)
    try:
        sku_id, _revision_id = _create_confirm_and_upload(client, "SEC-001")
        assert sku_id
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_published_sample_mutation_requires_valid_second_credential(monkeypatch):
    """Once a sample is published, further mutations (e.g. a new photo) are
    rejected without the credential, and accepted with it."""
    client, session_factory, engine = _client(monkeypatch)
    try:
        sku_id, revision_id = _create_confirm_and_upload(client, "SEC-002")
        _qualify_and_publish(client, session_factory, sku_id, revision_id)

        denied = client.post(
            "/admin/samples/upload",
            data={"sku_id": sku_id, "tenant_id": "default"},
            files={"image": ("flw2.png", _tiny_png(), "image/png")},
            headers=SURFACE_HEADERS,
        )
        assert denied.status_code == 403, denied.text

        wrong_key = client.post(
            "/admin/samples/upload",
            data={"sku_id": sku_id, "tenant_id": "default"},
            files={"image": ("flw2.png", _tiny_png(), "image/png")},
            headers=dict(SURFACE_HEADERS, **{"X-QC-Mutation-Key": "wrong-mutation-key"}),
        )
        assert wrong_key.status_code == 403, wrong_key.text

        accepted = client.post(
            "/admin/samples/upload",
            data={"sku_id": sku_id, "tenant_id": "default"},
            files={"image": ("flw2.png", _tiny_png(), "image/png")},
            headers=AUTHORIZED_HEADERS,
        )
        assert accepted.status_code == 200, accepted.text
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()


def test_sample_authoring_api_requires_sample_standard_surface(monkeypatch):
    client, _, engine = _client(monkeypatch)
    try:
        missing_surface = client.post(
            "/admin/studio/chat",
            json={"tenant_id": "default", "message": "create sku SEC-003"},
        )
        assert missing_surface.status_code == 403
        accepted = client.post(
            "/admin/studio/chat",
            json={"tenant_id": "default", "message": "create sku SEC-003"},
            headers=SURFACE_HEADERS,
        )
        assert accepted.status_code == 200
        assert accepted.json()["sku"]["item_number"] == "SEC-003"
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


def test_formal_publish_requires_second_credential_before_business_checks(monkeypatch):
    """Publish is unconditionally protected -- including a sample's first
    publish -- unlike entry/pre-publish edits."""
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
    """Credential separation is checked wherever the credential is enforced --
    exercised here via publish, which is always protected."""
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
            "/admin/studio/publish",
            json={"tenant_id": "demo", "sku_id": "missing"},
            headers={"X-QC-Mutation-Key": shared},
        )
        assert rejected.status_code == 400
        assert "must differ" in rejected.json()["detail"]
    finally:
        client.close()
        app.dependency_overrides.clear()
        engine.dispose()
