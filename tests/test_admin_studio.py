"""Tests for the Admin Studio — chat-first SKU + standard training (S2).

Maps to acceptance (PRD §16.1 / §17):
  * Chat message can create SKU.
  * Upload validated + displayed.
  * Missing counts trigger follow-up.
  * Confirmation persists method_hint / expected_value / pass_criteria.
  * Publish button creates signed bundle.

Plus the §5.1 "Minimum Admin Happy Path" (FLW-001, pearl/rhinestone counts)
exercised end-to-end.
"""
from __future__ import annotations

import struct
import zlib

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
from src.db.sku_models import QCDetectionPoint
from src.db.studio_models import QCPublishBundle

from src.api.main import app
from src.api.deps import get_db_dep
from src.qc_model.studio.service import verify_bundle


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autocommit=False, autoflush=False)
    engine.dispose()


@pytest.fixture()
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


def _tiny_png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _create_flw(client) -> str:
    resp = client.post(
        "/admin/studio/chat",
        json={"tenant_id": "default", "message": "create sku FLW-001 Flower Brooch"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == "created_sku"
    assert body["sku"]["item_number"] == "FLW-001"
    return body["sku"]["id"]


# ── Page ──────────────────────────────────────────────────────────────────────


def test_studio_page_renders(client):
    resp = client.get("/admin/studio")
    assert resp.status_code == 200
    assert "Admin Studio" in resp.text


# ── §5.2 SKU creation via chat ────────────────────────────────────────────────


def test_chat_creates_sku(client):
    sku_id = _create_flw(client)
    # It appears in the SKU list.
    resp = client.get("/admin/studio/skus?tenant_id=default")
    items = resp.json()["items"]
    assert any(i["id"] == sku_id and i["item_number"] == "FLW-001" for i in items)


def test_chat_existing_sku_is_selected_not_duplicated(client):
    _create_flw(client)
    resp = client.post(
        "/admin/studio/chat",
        json={"message": "create sku FLW-001 Flower Brooch"},
    )
    body = resp.json()
    assert body["action"] == "selected_sku"
    # Only one SKU exists.
    items = client.get("/admin/studio/skus").json()["items"]
    assert len([i for i in items if i["item_number"] == "FLW-001"]) == 1


def test_chat_without_sku_prompts_for_selection(client):
    resp = client.post("/admin/studio/chat", json={"message": "pearl count 3"})
    assert resp.json()["action"] == "need_sku"


# ── §5.4 Missing counts trigger follow-up ─────────────────────────────────────


def test_missing_counts_trigger_followup(client):
    sku_id = _create_flw(client)
    resp = client.post(
        "/admin/studio/chat",
        json={
            "message": "pearls and rhinestones with petal integrity",
            "sku_id": sku_id,
        },
    )
    body = resp.json()
    assert body["action"] == "follow_up"
    assert len(body["questions"]) >= 2
    codes = {cp["point_code"] for cp in body["confirmation_card"]["checkpoints"]}
    assert "PEARL_COUNT" in codes
    assert "RHINESTONE_COUNT" in codes
    # The count checkpoints have no guessed value.
    for cp in body["confirmation_card"]["checkpoints"]:
        if cp["point_code"] in ("PEARL_COUNT", "RHINESTONE_COUNT"):
            assert cp["expected_value"] is None


def test_counts_present_no_followup(client):
    sku_id = _create_flw(client)
    resp = client.post(
        "/admin/studio/chat",
        json={
            "message": "pearl count 3, rhinestone count 8, petal integrity",
            "sku_id": sku_id,
        },
    )
    body = resp.json()
    assert body["action"] == "extracted"
    assert body["questions"] == []


def test_confirm_rejects_counting_point_without_value(client):
    sku_id = _create_flw(client)
    card = client.post(
        "/admin/studio/chat",
        json={"message": "pearls only", "sku_id": sku_id},
    ).json()["confirmation_card"]
    resp = client.post(
        "/admin/studio/confirm",
        json={
            "intake_id": card["intake_id"],
            "confirmed_by": "alice",
            "checkpoints": card["checkpoints"],  # PEARL_COUNT still has no value
        },
    )
    assert resp.status_code == 400
    assert "expected count" in resp.json()["error"].lower()


# ── §5.5 Confirmation persists all semantic fields ────────────────────────────


def test_confirm_persists_all_semantic_fields(client, db_session_factory):
    sku_id = _create_flw(client)
    card = client.post(
        "/admin/studio/chat",
        json={
            "message": "pearl count 3, rhinestone count 8, stamen centering, petal integrity",
            "sku_id": sku_id,
        },
    ).json()["confirmation_card"]

    resp = client.post(
        "/admin/studio/confirm",
        json={
            "intake_id": card["intake_id"],
            "confirmed_by": "alice",
            "checkpoints": card["checkpoints"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["sku"]["standard_status"] == "standard_active"

    session = db_session_factory()
    try:
        dps = {
            dp.point_code: dp
            for dp in session.query(QCDetectionPoint)
            .filter_by(sku_id=sku_id, is_active=True)
            .all()
        }
    finally:
        session.close()

    pearl = dps["PEARL_COUNT"]
    assert pearl.method_hint == "counting"
    assert pearl.expected_value == "3"
    assert pearl.pass_criteria  # persisted, non-empty

    rhinestone = dps["RHINESTONE_COUNT"]
    assert rhinestone.expected_value == "8"
    assert rhinestone.pass_criteria


# ── §5.3 Upload validated + displayed ─────────────────────────────────────────


def test_upload_valid_png_displayed(client):
    sku_id = _create_flw(client)
    resp = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("standard.png", _tiny_png(), "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mime_type"] == "image/png"
    # Tied to current SKU and immediately previewable as the primary photo.
    assert body["sku"]["primary_photo"] is not None
    photo_url = body["url"]
    served = client.get(photo_url + "?tenant_id=default")
    assert served.status_code == 200


def test_upload_rejects_non_image(client):
    sku_id = _create_flw(client)
    resp = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        # Declares image/png but the bytes are not an image → MIME sniff rejects.
        files={"image": ("evil.png", b"#!/bin/sh\nrm -rf /", "image/png")},
    )
    assert resp.status_code == 415
    assert "image" in resp.json()["error"].lower()


def test_upload_rejects_oversize(client, monkeypatch):
    monkeypatch.setenv("QC_MAX_UPLOAD_BYTES", "10")
    sku_id = _create_flw(client)
    resp = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("big.png", _tiny_png(), "image/png")},
    )
    assert resp.status_code == 413


# ── §5.6 Publish → signed bundle ──────────────────────────────────────────────


def test_publish_creates_signed_bundle(client, db_session_factory):
    sku_id = _create_flw(client)
    card = client.post(
        "/admin/studio/chat",
        json={
            "message": "pearl count 3, rhinestone count 8, petal integrity",
            "sku_id": sku_id,
        },
    ).json()["confirmation_card"]
    client.post(
        "/admin/studio/confirm",
        json={
            "intake_id": card["intake_id"],
            "confirmed_by": "alice",
            "checkpoints": card["checkpoints"],
        },
    )

    resp = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert resp.status_code == 200, resp.text
    bundle = resp.json()["bundle"]
    assert bundle["signature_algorithm"] == "HMAC-SHA256"
    assert bundle["bundle_hash"]
    assert bundle["signature"]
    assert bundle["detection_point_count"] == 3

    # Appears in bundle history and the signature verifies over the manifest.
    history = client.get(f"/admin/studio/skus/{sku_id}/bundles").json()["bundles"]
    assert len(history) == 1

    session = db_session_factory()
    try:
        stored = session.query(QCPublishBundle).one()
        assert verify_bundle(stored.manifest_json, stored.signature)
        # Manifest carries every semantic field for each detection point.
        dp = stored.manifest_json["detection_points"][0]
        assert {"method_hint", "expected_value", "pass_criteria"} <= set(dp.keys())
    finally:
        session.close()


def test_publish_fails_closed_without_confirmed_standard(client):
    sku_id = _create_flw(client)
    # No detection points confirmed yet.
    resp = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert resp.status_code == 400
    assert "publish" in resp.json()["error"].lower()


# ── §5.1 Minimum Admin Happy Path (FLW-001) end-to-end ────────────────────────


def test_minimum_admin_happy_path_flw001(client):
    # 1. Create SKU by chat.
    sku_id = _create_flw(client)

    # 2. Upload a standard photo.
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    assert up.status_code == 200

    # 3. Describe requirements without counts → follow-up.
    follow = client.post(
        "/admin/studio/chat",
        json={"message": "pearls and rhinestones on the petals", "sku_id": sku_id},
    ).json()
    assert follow["action"] == "follow_up"

    # 4. Provide the counts → clean confirmation card.
    card = client.post(
        "/admin/studio/chat",
        json={"message": "pearl count 3, rhinestone count 8", "sku_id": sku_id},
    ).json()["confirmation_card"]

    # 5. Confirm.
    conf = client.post(
        "/admin/studio/confirm",
        json={
            "intake_id": card["intake_id"],
            "confirmed_by": "admin",
            "checkpoints": card["checkpoints"],
        },
    )
    assert conf.status_code == 200

    # 6. Publish signed bundle.
    pub = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert pub.status_code == 200
    assert pub.json()["bundle"]["detection_point_count"] == 2
