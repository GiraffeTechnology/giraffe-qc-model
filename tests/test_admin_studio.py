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
import src.db.training_models     # noqa: F401
from src.db.sku_models import QCDetectionPoint
from src.db.studio_models import QCPublishBundle

from src.api.main import app
from src.api.deps import get_db_dep
from src.db.sku_models import QCSkuItem
from src.qc_model.studio.service import process_structured_ai_turn, sku_summary, verify_bundle
from src.qc_model.qualification import probation as probation_service


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


def _qualify_training(db_session_factory, sku_id: str, tenant_id: str = "default") -> None:
    """Directly insert a qualifying rolling window (29 reviewed, alternating
    qualified/unqualified, zero false passes) of training judgments against
    the SKU's *current* active standard revision, so publish-focused tests
    don't each need to mock 29 individual CV+VLM training calls -- the
    training gate's own logic is exhaustively covered by
    tests/test_training_gate.py."""
    import uuid
    from datetime import datetime, timedelta, timezone

    from src.db.sku_models import QCSkuStandardRevision
    from src.db.training_models import QCTrainingJudgment

    session = db_session_factory()
    try:
        revision = (
            session.query(QCSkuStandardRevision)
            .filter_by(sku_id=sku_id, tenant_id=tenant_id, status="active")
            .order_by(QCSkuStandardRevision.revision_no.desc())
            .first()
        )
        assert revision is not None, "no active standard revision to qualify training for"
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(29):
            session.add(QCTrainingJudgment(
                id=uuid.uuid4().hex, tenant_id=tenant_id, sku_id=sku_id,
                standard_revision_id=revision.id,
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


# ── Page ──────────────────────────────────────────────────────────────────────


def test_studio_page_renders(client):
    resp = client.get("/admin/studio")
    assert resp.status_code == 200
    assert "Admin Studio" in resp.text
    assert "1 Training" in resp.text
    assert "2 Publish" in resp.text
    assert "1 SKU" not in resp.text
    assert "Reference photo" not in resp.text


def test_sample_page_shows_sample_entry_and_detection_confirmation_workflow(client):
    sku_id = _create_flw(client)
    page = client.get(f"/admin/samples/{sku_id}")
    assert "1 Sample entry" in page.text
    assert "2 Detection-point confirmation" in page.text


def test_sample_created_for_tenant_is_available_in_existing_studio(client):
    client.post(
        "/admin/samples",
        data={"tenant_id": "demo", "item_number": "HANDOFF-001", "name": "Studio handoff"},
    )
    page = client.get("/admin/studio?tenant_id=demo")
    assert 'data-tenant="demo"' in page.text
    items = client.get("/admin/studio/skus?tenant_id=demo").json()["items"]
    assert any(item["item_number"] == "HANDOFF-001" for item in items)


def test_sample_workbench_owns_three_authoring_inputs_and_confirmation(client):
    created = client.post(
        "/admin/samples",
        follow_redirects=False,
        data={"tenant_id": "demo", "item_number": "HANDOFF-002", "name": "Studio handoff"},
    )
    sku_id = created.headers["location"].split("/")[-1].split("?")[0]
    detail = client.get(created.headers["location"])
    assert f'data-sku-id="{sku_id}"' in detail.text
    assert 'id="sample-authoring-text"' in detail.text
    assert 'id="sample-process-card-toggle"' in detail.text
    assert 'id="sample-standard-file-toggle"' in detail.text
    assert 'id="sample-confirm-card-template"' in detail.text
    assert '/static/sample_standard_authoring.js' in detail.text
    page = client.get(f"/admin/studio?tenant_id=demo&sku_id={sku_id}")
    assert f'data-initial-sku="{sku_id}"' in page.text
    assert 'id="chat-text"' not in page.text
    assert 'id="process-card-toggle"' not in page.text
    assert 'id="standard-file-toggle"' not in page.text
    assert 'id="confirm-card-template"' not in page.text


def _structured_import_result():
    return {
        "intent": "define_requirements",
        "reply": "Structured draft ready.",
        "sku": {},
        "questions": [],
        "checkpoints": [{
            "point_code": "STONE_COUNT", "label": "Stone count",
            "description": "Count stones", "method_hint": "counting",
            "severity": "major", "expected_value": "7",
            "pass_criteria": "Exactly 7", "expected_features": {}, "cv_config": {},
        }],
        "assistant": {"role": "text", "provider": "test", "model": "text-9b", "elapsed_ms": 1, "mode": "live"},
    }


def test_text_standard_file_is_always_structured_by_text_assistant(client, monkeypatch):
    from src.qc_model.studio import ai_gateway

    sku_id = _create_flw(client)
    seen = {}
    monkeypatch.setattr(ai_gateway, "text_config", lambda: type("C", (), {"configured": True})())
    def fake_author_text(**kwargs):
        seen.update(kwargs)
        return _structured_import_result()
    monkeypatch.setattr(ai_gateway, "author_text", fake_author_text)
    response = client.post(
        "/admin/studio/import-standard",
        data={"tenant_id": "default", "sku_id": sku_id, "source_kind": "file"},
        files={"document": ("standard.txt", "7 rhinestones; missing one is rejected", "text/plain")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assistant"]["model"] == "text-9b"
    assert body["import"]["ocr_used"] is False
    assert "7 rhinestones" in seen["message"]
    assert body["confirmation_card"]["checkpoints"][0]["expected_value"] == "7"


def test_process_card_image_runs_ocr_before_text_assistant(client, monkeypatch):
    from src.qc_model.studio import ai_gateway

    sku_id = _create_flw(client)
    calls = []
    monkeypatch.setattr(ai_gateway, "vision_config", lambda: type("C", (), {"configured": True})())
    monkeypatch.setattr(ai_gateway, "text_config", lambda: type("C", (), {"configured": True})())
    def fake_ocr(**kwargs):
        calls.append("ocr")
        return {"text": "3 pearls and 7 rhinestones", "assistant": {"model": "ocr"}}
    def fake_text(**kwargs):
        calls.append("9b")
        assert "3 pearls and 7 rhinestones" in kwargs["message"]
        return _structured_import_result()
    monkeypatch.setattr(ai_gateway, "extract_image_text", fake_ocr)
    monkeypatch.setattr(ai_gateway, "author_text", fake_text)
    response = client.post(
        "/admin/studio/import-standard",
        data={"tenant_id": "default", "sku_id": sku_id, "source_kind": "process_card"},
        files={"document": ("card.png", _tiny_png(), "image/png")},
    )
    assert response.status_code == 200, response.text
    assert calls == ["ocr", "9b"]
    assert response.json()["import"]["ocr_used"] is True


def test_scanned_pdf_renders_then_runs_ocr_before_text_assistant(client, monkeypatch):
    from pathlib import Path
    from src.api import qc_studio_router
    from src.qc_model.studio import ai_gateway

    sku_id = _create_flw(client)
    calls = []
    monkeypatch.setattr(qc_studio_router, "extract_process_card_text", lambda path: None)
    monkeypatch.setattr(ai_gateway, "vision_config", lambda: type("C", (), {"configured": True})())
    monkeypatch.setattr(ai_gateway, "text_config", lambda: type("C", (), {"configured": True})())
    def fake_render(args, **kwargs):
        Path(args[-1] + "-1.png").write_bytes(_tiny_png())
        return type("Completed", (), {"returncode": 0})()
    def fake_ocr(**kwargs):
        calls.append("ocr")
        return {"text": "4 petals", "assistant": {"model": "ocr"}}
    def fake_text(**kwargs):
        calls.append("9b")
        assert "4 petals" in kwargs["message"]
        return _structured_import_result()
    monkeypatch.setattr(qc_studio_router.subprocess, "run", fake_render)
    monkeypatch.setattr(ai_gateway, "extract_image_text", fake_ocr)
    monkeypatch.setattr(ai_gateway, "author_text", fake_text)
    response = client.post(
        "/admin/studio/import-standard",
        data={"tenant_id": "default", "sku_id": sku_id, "source_kind": "process_card"},
        files={"document": ("scanned.pdf", b"%PDF-scanned", "application/pdf")},
    )
    assert response.status_code == 200, response.text
    assert calls == ["ocr", "9b"]
    assert response.json()["import"]["ocr_used"] is True


def test_import_rejects_unconvertible_file_before_text_assistant(client, monkeypatch):
    from src.qc_model.studio import ai_gateway

    sku_id = _create_flw(client)
    monkeypatch.setattr(ai_gateway, "author_text", lambda **kwargs: pytest.fail("9B must not receive unreadable input"))
    response = client.post(
        "/admin/studio/import-standard",
        data={"tenant_id": "default", "sku_id": sku_id, "source_kind": "file"},
        files={"document": ("drawing.dxf", b"not-rendered", "application/dxf")},
    )
    assert response.status_code == 415


def test_studio_config_exposes_shared_seven_state_lifecycle(client):
    resp = client.get("/admin/studio/config")
    assert resp.status_code == 200
    assert resp.json()["sku_lifecycle_states"] == [
        "draft",
        "needs_information",
        "ready_for_review",
        "confirmed",
        "published",
        "installed",
        "needs_requalification",
    ]


def test_structured_studio_create_starts_in_draft(client):
    resp = client.post(
        "/admin/studio/skus",
        json={"item_number": "FORM-001", "name": "Form-created SKU"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "draft"


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


def test_checkpoint_free_turn_never_leaves_a_confirmable_draft(db_session_factory):
    """UI audit (2026-07-22): author_image always returns checkpoints=[]
    (photo analysis never seeds candidates) but often returns non-empty
    questions. That combination must not create a lingering
    pending_confirmation intake — one used to resurface later, on an
    unrelated sku_summary() call, as an empty confirm card with nothing
    for the admin to accept or reject."""
    import uuid
    from datetime import datetime, timezone

    db = db_session_factory()
    try:
        sku = QCSkuItem(
            id=uuid.uuid4().hex, tenant_id="default", item_number="FLW-EMPTY",
            name="Empty checkpoint test", status="draft",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        db.add(sku)
        db.commit()

        ai_result = {
            "intent": "provide_details",
            "reply": "The photo shows a flower brooch.",
            "sku": {},
            "checkpoints": [],
            "questions": [{"field": "standard", "question": "What is the item number?"}],
        }
        result = process_structured_ai_turn(
            db, tenant_id="default", message="photo upload",
            ai_result=ai_result, current_sku_id=sku.id,
        )
        assert result.confirmation_card is None
        assert result.action == "follow_up"

        # The regression: a later, unrelated summary call must not resurface
        # this checkpoint-free draft as something pending confirmation.
        summary = sku_summary(db, sku)
        assert summary["pending_confirmation"] is None
    finally:
        db.close()


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
    cv_checkpoint = next(
        cp for cp in card["checkpoints"] if cp.get("method_hint") != "counting"
    )
    cv_checkpoint["expected_features"] = {"pistil_localization.found": True}
    cv_checkpoint["cv_config"] = {
        "analyzers": [{"name": "pistil_localization", "params": {}}],
    }
    cv_point_code = cv_checkpoint["point_code"]

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

    cv_point = dps[cv_point_code]
    assert cv_point.expected_features_json == {"pistil_localization.found": True}
    assert cv_point.cv_config_json == {
        "analyzers": [{"name": "pistil_localization", "params": {}}],
    }


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
    # The upload response URL is tenant-aware and resolves as-is.
    photo_url = body["url"]
    assert "tenant_id=default" in photo_url
    served = client.get(photo_url)
    assert served.status_code == 200


def test_sample_workbench_assets_capture_usb_standard_sample_and_review_drafts():
    """Sample capture and draft review stay together in sample management."""
    root = __import__("pathlib").Path(__file__).resolve().parent.parent
    html = (root / "src/web/templates/sample_detail.html").read_text()
    camera = (root / "src/web/static/sample_camera.js").read_text()
    authoring = (root / "src/web/static/sample_standard_authoring.js").read_text()

    assert 'id="sample-camera-preview"' in html
    assert 'id="sample-camera-capture"' in html
    assert 'id="sample-camera-upload-confirm"' in html
    assert 'id="sample-camera-retake"' in html
    assert "navigator.mediaDevices.getUserMedia" in camera
    assert "navigator.mediaDevices.enumerateDevices" in camera
    assert ".drawImage(" in camera
    assert ".toBlob(" in camera
    assert 'id="sample-confirm-card-template"' in html
    assert "card.coverage_review" in authoring
    assert "coverageComplete" in html
    assert "coverageIncomplete" in html


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


# ── Tenant-aware standard-photo URLs (Codex P2 regression) ────────────────────


def test_standard_photo_urls_are_tenant_aware_for_non_default_tenant(client):
    """A non-default tenant's standard photo must preview without a 404.

    Regression for the Codex P2: previously the generated preview URL omitted
    ``tenant_id``, so the serving route (which defaults it to ``default``)
    404'd on photos owned by another tenant.
    """
    tenant = "tenant_acme"

    # 1. Create SKU FLW-001 under the non-default tenant (via chat).
    created = client.post(
        "/admin/studio/chat",
        json={"tenant_id": tenant, "message": "create sku FLW-001 Flower Brooch"},
    ).json()
    assert created["action"] == "created_sku"
    sku_id = created["sku"]["id"]

    # 2. Upload one standard photo through the Studio upload path.
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": tenant},
        files={"image": ("acme.png", _tiny_png(), "image/png")},
    )
    assert up.status_code == 200, up.text
    up_body = up.json()

    # 3. The upload response preview URL carries the owning tenant.
    upload_url = up_body["url"]
    assert f"tenant_id={tenant}" in upload_url

    # 4. The SKU summary/list used by the right panel carries the same URL.
    summary = client.get(f"/admin/studio/skus/{sku_id}?tenant_id={tenant}").json()
    summary_url = summary["primary_photo"]["url"]
    assert f"tenant_id={tenant}" in summary_url
    assert summary_url == upload_url
    for p in summary["photos"]:
        assert f"tenant_id={tenant}" in p["url"]

    listed = client.get(f"/admin/studio/skus?tenant_id={tenant}").json()["items"]
    listed_sku = next(i for i in listed if i["id"] == sku_id)
    assert f"tenant_id={tenant}" in listed_sku["primary_photo"]["url"]

    # 5. Fetching the tenant-aware URL resolves (200, not 404).
    served = client.get(summary_url)
    assert served.status_code == 200

    # 6. Tenant isolation stays fail-closed: the same photo id under the wrong
    #    tenant (or the route default) must not return the photo.
    photo_id = up_body["photo_id"]
    assert client.get(f"/admin/studio/photos/{photo_id}?tenant_id=default").status_code == 404
    assert client.get(f"/admin/studio/photos/{photo_id}").status_code == 404
    assert client.get(f"/admin/studio/photos/{photo_id}?tenant_id=other").status_code == 404


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

    _qualify_training(db_session_factory, sku_id)
    resp = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert resp.status_code == 200, resp.text
    bundle = resp.json()["bundle"]
    assert bundle["signature_algorithm"] == "ed25519"
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


def test_publish_builds_verifiable_ed25519_tar_gz(client, db_session_factory):
    """The canonical bundle is an Ed25519-signed .tar.gz embedding the photos."""
    from src.qc_model.studio.service import build_publish_archive
    from src.qc_model.bundle import ed25519

    sku_id = _create_flw(client)
    client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    card = client.post(
        "/admin/studio/chat",
        json={"message": "pearl count 3, rhinestone count 8", "sku_id": sku_id},
    ).json()["confirmation_card"]
    client.post(
        "/admin/studio/confirm",
        json={"intake_id": card["intake_id"], "confirmed_by": "a", "checkpoints": card["checkpoints"]},
    )

    session = db_session_factory()
    try:
        archive = build_publish_archive(session, sku_id, "default")
    finally:
        session.close()

    # The archive verifies fail-closed and carries the manifest + a photo payload.
    manifest = ed25519.verify_signed_archive(archive.archive_bytes)
    assert manifest["sku"]["item_number"] == "FLW-001"
    assert len(manifest["detection_points"]) == 2

    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(archive.archive_bytes), mode="r:gz") as tar:
        names = tar.getnames()
    assert "manifest.json" in names and "checksum.sha256" in names and "bundle.sig" in names
    assert any(n.startswith("photos/") for n in names)


def test_publish_archive_fails_closed_on_missing_photo_file(client, db_session_factory):
    """A declared standard photo whose file is gone blocks publish (no partial bundle)."""
    import os
    from src.qc_model.studio.service import build_publish_archive
    from src.db.sku_models import QCStandardPhoto

    sku_id = _create_flw(client)
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    ).json()
    card = client.post(
        "/admin/studio/chat",
        json={"message": "pearl count 3", "sku_id": sku_id},
    ).json()["confirmation_card"]
    client.post(
        "/admin/studio/confirm",
        json={"intake_id": card["intake_id"], "confirmed_by": "a", "checkpoints": card["checkpoints"]},
    )

    session = db_session_factory()
    try:
        photo = session.query(QCStandardPhoto).filter_by(id=up["photo_id"]).one()
        os.remove(photo.local_path)  # the file disappears from disk
        with pytest.raises(ValueError) as exc:
            build_publish_archive(session, sku_id, "default")
        assert "missing" in str(exc.value).lower()
    finally:
        session.close()


def test_publish_archive_fails_closed_on_stale_photo(client, db_session_factory):
    """A standard photo whose bytes drifted from its recorded checksum blocks publish."""
    from src.qc_model.studio.service import build_publish_archive
    from src.db.sku_models import QCStandardPhoto

    sku_id = _create_flw(client)
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    ).json()
    card = client.post(
        "/admin/studio/chat",
        json={"message": "pearl count 3", "sku_id": sku_id},
    ).json()["confirmation_card"]
    client.post(
        "/admin/studio/confirm",
        json={"intake_id": card["intake_id"], "confirmed_by": "a", "checkpoints": card["checkpoints"]},
    )

    session = db_session_factory()
    try:
        photo = session.query(QCStandardPhoto).filter_by(id=up["photo_id"]).one()
        with open(photo.local_path, "wb") as fh:
            fh.write(b"different bytes than the recorded sha256")
        with pytest.raises(ValueError) as exc:
            build_publish_archive(session, sku_id, "default")
        assert "stale" in str(exc.value).lower() or "checksum" in str(exc.value).lower()
    finally:
        session.close()


def test_publish_endpoint_fails_closed_on_missing_photo(client, db_session_factory):
    """The real /admin/studio/publish endpoint (not just the helper) rejects a
    missing photo — the archive validation is wired into publish."""
    import os
    from src.db.sku_models import QCStandardPhoto

    sku_id = _create_flw(client)
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    ).json()
    card = client.post(
        "/admin/studio/chat",
        json={"message": "pearl count 3, rhinestone count 8", "sku_id": sku_id},
    ).json()["confirmation_card"]
    client.post(
        "/admin/studio/confirm",
        json={"intake_id": card["intake_id"], "confirmed_by": "a", "checkpoints": card["checkpoints"]},
    )

    # The photo file disappears from disk, then publish is attempted via the API.
    session = db_session_factory()
    try:
        path = session.query(QCStandardPhoto).filter_by(id=up["photo_id"]).one().local_path
    finally:
        session.close()
    os.remove(path)

    resp = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert resp.status_code == 400, resp.text
    assert "missing" in resp.json()["error"].lower()
    # And nothing was persisted.
    assert client.get(f"/admin/studio/skus/{sku_id}/bundles").json()["bundles"] == []


def test_publish_archive_fails_closed_on_missing_sha256(client, db_session_factory):
    """A standard photo with no recorded sha256 cannot be published — its payload
    would be unverifiable at import time (Codex P2)."""
    from src.qc_model.studio.service import build_publish_archive
    from src.db.sku_models import QCStandardPhoto

    sku_id = _create_flw(client)
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    ).json()
    card = client.post(
        "/admin/studio/chat",
        json={"message": "pearl count 3", "sku_id": sku_id},
    ).json()["confirmation_card"]
    client.post(
        "/admin/studio/confirm",
        json={"intake_id": card["intake_id"], "confirmed_by": "a", "checkpoints": card["checkpoints"]},
    )

    session = db_session_factory()
    try:
        photo = session.query(QCStandardPhoto).filter_by(id=up["photo_id"]).one()
        photo.sha256 = ""  # checksum lost / never recorded
        session.commit()
        with pytest.raises(ValueError) as exc:
            build_publish_archive(session, sku_id, "default")
        assert "sha256" in str(exc.value).lower()
    finally:
        session.close()


def _publish_flw(client, sku_id, db_session_factory):
    card = client.post(
        "/admin/studio/chat",
        json={"message": "pearl count 3, rhinestone count 8", "sku_id": sku_id},
    ).json()["confirmation_card"]
    client.post(
        "/admin/studio/confirm",
        json={"intake_id": card["intake_id"], "confirmed_by": "a", "checkpoints": card["checkpoints"]},
    )
    _qualify_training(db_session_factory, sku_id)
    return client.post("/admin/studio/publish", json={"sku_id": sku_id}).json()["bundle"]


def test_publish_persists_downloadable_verified_archive(client, db_session_factory):
    """Publish persists the canonical signed .tar.gz; the download endpoint serves
    it and it re-verifies fail-closed (Codex P1 — archive must not be discarded)."""
    import io
    import tarfile
    from src.qc_model.bundle import ed25519

    sku_id = _create_flw(client)
    client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    bundle = _publish_flw(client, sku_id, db_session_factory)
    assert bundle["download_url"].startswith(f"/admin/studio/bundles/{bundle['id']}/download")

    dl = client.get(bundle["download_url"])
    assert dl.status_code == 200, dl.text
    assert dl.headers["content-type"].startswith("application/gzip")

    # The bytes we serve are the canonical archive: they verify against the
    # Ed25519 public key and carry the embedded photo payload.
    manifest = ed25519.verify_signed_archive(dl.content)
    assert manifest["sku"]["item_number"] == "FLW-001"
    with tarfile.open(fileobj=io.BytesIO(dl.content), mode="r:gz") as tar:
        names = tar.getnames()
    assert any(n.startswith("photos/") for n in names)


def test_download_bundle_is_tenant_scoped(client, db_session_factory):
    """A bundle published under one tenant is not downloadable under another."""
    sku_id = _create_flw(client)
    client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    bundle = _publish_flw(client, sku_id, db_session_factory)
    resp = client.get(f"/admin/studio/bundles/{bundle['id']}/download?tenant_id=other")
    assert resp.status_code == 404


def test_download_bundle_fails_closed_on_tampered_payload(client, db_session_factory):
    """If the stored archive is corrupted at rest, download refuses to serve it."""
    from src.qc_model.studio.service import _bundle_archive_path

    sku_id = _create_flw(client)
    client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    bundle = _publish_flw(client, sku_id, db_session_factory)

    # Corrupt the archive on disk (simulate at-rest tampering).
    path = _bundle_archive_path("default", bundle["id"])
    path.write_bytes(b"not a valid tar.gz")

    resp = client.get(bundle["download_url"])
    assert resp.status_code == 409


# ── §5.1 Minimum Admin Happy Path (FLW-001) end-to-end ────────────────────────


def test_minimum_admin_happy_path_flw001(client, db_session_factory):
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
    _qualify_training(db_session_factory, sku_id)
    pub = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert pub.status_code == 200
    assert pub.json()["bundle"]["detection_point_count"] == 2


# ── Region annotation (§2, WS6) — real HTTP caller for set_detection_point_regions ──


def _confirm_one_point(client, sku_id: str) -> str:
    """Create+confirm a single detection point, return its id."""
    card = client.post(
        "/admin/studio/chat",
        json={"message": "stamen centering", "sku_id": sku_id},
    ).json()["confirmation_card"]
    resp = client.post(
        "/admin/studio/confirm",
        json={
            "intake_id": card["intake_id"],
            "confirmed_by": "admin",
            "checkpoints": card["checkpoints"],
        },
    )
    assert resp.status_code == 200, resp.text
    dps = resp.json()["sku"]["detection_points"]
    assert len(dps) == 1
    return dps[0]["id"]


def test_set_regions_persists_and_appears_in_sku_summary(client):
    sku_id = _create_flw(client)
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    photo_id = up.json()["photo_id"]
    dp_id = _confirm_one_point(client, sku_id)

    resp = client.post(
        f"/admin/studio/detection-points/{dp_id}/regions",
        json={"regions": [{"image_id": photo_id, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "regions_saved"
    assert body["regions"] == [{"image_id": photo_id, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]

    sku = client.get(f"/admin/studio/skus/{sku_id}").json()
    saved = next(d for d in sku["detection_points"] if d["id"] == dp_id)
    assert saved["regions"] == [{"image_id": photo_id, "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]


def test_set_regions_rejects_unknown_photo_fail_closed(client):
    sku_id = _create_flw(client)
    dp_id = _confirm_one_point(client, sku_id)
    resp = client.post(
        f"/admin/studio/detection-points/{dp_id}/regions",
        json={"regions": [{"image_id": "not-a-real-photo", "x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}]},
    )
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_set_regions_empty_list_clears_existing(client):
    sku_id = _create_flw(client)
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    photo_id = up.json()["photo_id"]
    dp_id = _confirm_one_point(client, sku_id)

    client.post(
        f"/admin/studio/detection-points/{dp_id}/regions",
        json={"regions": [{"image_id": photo_id, "x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}]},
    )
    resp = client.post(f"/admin/studio/detection-points/{dp_id}/regions", json={"regions": []})
    assert resp.status_code == 200
    assert resp.json()["regions"] == []


def test_published_bundle_manifest_contains_authored_regions(client, db_session_factory):
    """Closes the gap: proves regions set via the real endpoint actually reach
    the signed publish bundle, not just _dp_view (already covered by
    tests/test_region_annotation.py's unit test)."""
    import io
    import json
    import tarfile

    sku_id = _create_flw(client)
    up = client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    photo_id = up.json()["photo_id"]
    dp_id = _confirm_one_point(client, sku_id)

    region = {"image_id": photo_id, "x": 0.25, "y": 0.25, "w": 0.5, "h": 0.5}
    set_resp = client.post(
        f"/admin/studio/detection-points/{dp_id}/regions",
        json={"regions": [region]},
    )
    assert set_resp.status_code == 200, set_resp.text

    _qualify_training(db_session_factory, sku_id)
    pub = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert pub.status_code == 200, pub.text
    bundle_id = pub.json()["bundle"]["id"]

    dl = client.get(f"/admin/studio/bundles/{bundle_id}/download")
    assert dl.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(dl.content), mode="r:gz") as tf:
        manifest_bytes = tf.extractfile("manifest.json").read()
    manifest = json.loads(manifest_bytes)
    dp_manifest = next(d for d in manifest["detection_points"] if d["point_code"] == "STAMEN_CENTERING")
    assert dp_manifest["regions"] == [region]


def test_analysis_config_real_endpoint_persists_and_bundle_carries_hooks(client, db_session_factory):
    """WS6 v2: authored expected_features/cv_config reach the signed manifest."""
    import io
    import json
    import tarfile

    sku_id = _create_flw(client)
    client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    dp_id = _confirm_one_point(client, sku_id)
    expected = {"rhinestone_count": 24}
    # min_area_px is the real analyzer parameter (src.cv_preanalysis.analyzers);
    # a stale "min_area" key here would now be rejected as unrecognized (§8.1 P0 fix).
    cv_config = {"analyzers": [{"name": "rhinestone_count", "params": {"min_area_px": 8}}]}
    saved = client.post(
        f"/admin/studio/detection-points/{dp_id}/analysis-config",
        json={"expected_features": expected, "cv_config": cv_config},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["expected_features"] == expected
    assert saved.json()["cv_config"] == cv_config

    _qualify_training(db_session_factory, sku_id)
    published = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert published.status_code == 200, published.text
    bundle_id = published.json()["bundle"]["id"]
    archive = client.get(f"/admin/studio/bundles/{bundle_id}/download")
    with tarfile.open(fileobj=io.BytesIO(archive.content), mode="r:gz") as tf:
        manifest = json.loads(tf.extractfile("manifest.json").read())
    point = next(item for item in manifest["detection_points"] if item["point_code"] == "STAMEN_CENTERING")
    assert point["expected_features"] == expected
    assert point["cv_config"] == cv_config


def test_analysis_config_rejects_unknown_analyzer(client):
    sku_id = _create_flw(client)
    dp_id = _confirm_one_point(client, sku_id)
    response = client.post(
        f"/admin/studio/detection-points/{dp_id}/analysis-config",
        json={"cv_config": {"analyzers": [{"name": "vendor_magic", "params": {}}]}},
    )
    assert response.status_code == 400
    assert "unsupported analyzer" in response.json()["error"]


def test_analysis_config_change_after_publish_requires_new_revision(client, db_session_factory):
    sku_id = _create_flw(client)
    client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    dp_id = _confirm_one_point(client, sku_id)
    _qualify_training(db_session_factory, sku_id)
    assert client.post("/admin/studio/publish", json={"sku_id": sku_id}).status_code == 200
    response = client.post(
        f"/admin/studio/detection-points/{dp_id}/analysis-config",
        json={"expected_features": {"petal_count": 5}},
    )
    assert response.status_code == 400
    assert "new revision" in response.json()["error"]


def test_published_detection_point_semantic_edit_requires_new_revision(client, db_session_factory):
    sku_id = _create_flw(client)
    client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    dp_id = _confirm_one_point(client, sku_id)
    _qualify_training(db_session_factory, sku_id)
    assert client.post("/admin/studio/publish", json={"sku_id": sku_id}).status_code == 200
    point = client.get(f"/admin/studio/skus/{sku_id}").json()["detection_points"][0]
    semantic = client.patch(f"/admin/studio/detection-points/{dp_id}", json={
        "point_code": point["point_code"], "label": point["label"],
        "description": point["description"], "method_hint": point["method_hint"],
        "expected_value": "changed", "severity": point["severity"],
    })
    assert semantic.status_code == 409
    assert "new qualified revision" in semantic.json()["detail"]


def test_published_detection_point_description_edit_preserves_revision(client, db_session_factory):
    sku_id = _create_flw(client)
    client.post(
        "/admin/studio/upload",
        data={"sku_id": sku_id, "tenant_id": "default"},
        files={"image": ("flw.png", _tiny_png(), "image/png")},
    )
    dp_id = _confirm_one_point(client, sku_id)
    _qualify_training(db_session_factory, sku_id)
    assert client.post("/admin/studio/publish", json={"sku_id": sku_id}).status_code == 200
    point = client.get(f"/admin/studio/skus/{sku_id}").json()["detection_points"][0]
    preserved = client.patch(f"/admin/studio/detection-points/{dp_id}", json={
        "point_code": point["point_code"], "label": point["label"],
        "description": "clarified wording only", "method_hint": point["method_hint"],
        "expected_value": point["expected_value"], "severity": point["severity"],
    })
    assert preserved.status_code == 200, preserved.text
    assert preserved.json()["description"] == "clarified wording only"


# ── Probation auto-start on publish (WS7 §1.1) ────────────────────────────────


def test_publish_starts_probation(client, db_session_factory):
    """Publishing is exactly "newly installed" (PRD §3.2) -- the real
    /admin/studio/publish endpoint must call start_probation(), not just the
    standalone service function."""
    sku_id = _create_flw(client)
    _confirm_one_point(client, sku_id)
    _qualify_training(db_session_factory, sku_id)
    pub = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert pub.status_code == 200, pub.text
    rev_id = pub.json()["bundle"]["standard_revision_id"]

    resp = client.get(f"/api/qc/probation/by-revision/{rev_id}")
    assert resp.status_code == 200, resp.text
    p = resp.json()
    assert p["status"] == "active"
    assert p["sku_id"] == sku_id
    assert p["gate"]["jobs_recorded"] == 0


def test_republish_same_revision_preserves_probation_progress(client, db_session_factory):
    """Re-publishing without a new confirm reuses the same standard_revision_id
    -- get-or-create must return the existing probation record, not reset it."""
    sku_id = _create_flw(client)
    _confirm_one_point(client, sku_id)
    _qualify_training(db_session_factory, sku_id)
    pub1 = client.post("/admin/studio/publish", json={"sku_id": sku_id}).json()["bundle"]
    rev_id = pub1["standard_revision_id"]

    session = db_session_factory()
    try:
        probation = probation_service.get_probation_for_revision(session, rev_id, "default")
        probation_service.record_probation_job(session, probation.id, "pass", "pass", "default", job_ref="j1")
    finally:
        session.close()

    # Same active revision as pub1 -- its training window still qualifies.
    pub2 = client.post("/admin/studio/publish", json={"sku_id": sku_id}).json()["bundle"]
    assert pub2["standard_revision_id"] == rev_id  # no new confirm -> same active revision

    p = client.get(f"/api/qc/probation/by-revision/{rev_id}").json()
    assert p["gate"]["jobs_recorded"] == 1


def test_new_revision_after_reconfirm_gets_fresh_probation(client, db_session_factory):
    """Editing/re-confirming a standard mints a brand-new standard_revision_id
    (§3.4) -- the fresh id naturally gets a fresh probation record at 0
    through start_probation's own get-or-create keying, with no separate
    reset codepath needed."""
    sku_id = _create_flw(client)
    _confirm_one_point(client, sku_id)
    _qualify_training(db_session_factory, sku_id)
    pub1 = client.post("/admin/studio/publish", json={"sku_id": sku_id}).json()["bundle"]
    rev1 = pub1["standard_revision_id"]

    session = db_session_factory()
    try:
        probation = probation_service.get_probation_for_revision(session, rev1, "default")
        probation_service.record_probation_job(session, probation.id, "pass", "pass", "default", job_ref="j1")
    finally:
        session.close()

    _confirm_one_point(client, sku_id)  # a fresh confirm -> a brand-new revision
    _qualify_training(db_session_factory, sku_id)  # the new revision needs its own qualifying window
    pub2 = client.post("/admin/studio/publish", json={"sku_id": sku_id}).json()["bundle"]
    rev2 = pub2["standard_revision_id"]
    assert rev2 != rev1

    p2 = client.get(f"/api/qc/probation/by-revision/{rev2}").json()
    assert p2["gate"]["jobs_recorded"] == 0


def test_probation_pause_resume_via_real_studio_endpoints(client, db_session_factory):
    sku_id = _create_flw(client)
    _confirm_one_point(client, sku_id)
    _qualify_training(db_session_factory, sku_id)
    pub = client.post("/admin/studio/publish", json={"sku_id": sku_id}).json()["bundle"]
    rev_id = pub["standard_revision_id"]
    probation_id = client.get(f"/api/qc/probation/by-revision/{rev_id}").json()["probation_id"]

    paused = client.post(f"/api/qc/probation/{probation_id}/pause").json()
    assert paused["status"] == "paused"
    resumed = client.post(f"/api/qc/probation/{probation_id}/resume").json()
    assert resumed["status"] == "active"


def test_probation_disagreement_report_endpoint(client, db_session_factory):
    sku_id = _create_flw(client)
    _confirm_one_point(client, sku_id)
    _qualify_training(db_session_factory, sku_id)
    pub = client.post("/admin/studio/publish", json={"sku_id": sku_id}).json()["bundle"]
    rev_id = pub["standard_revision_id"]
    probation_id = client.get(f"/api/qc/probation/by-revision/{rev_id}").json()["probation_id"]

    session = db_session_factory()
    try:
        probation = probation_service.get_probation(session, probation_id, "default")
        probation_service.record_probation_job(
            session, probation.id, "pass", "fail", "default", job_ref="j1",
            point_disagreements=[{"point_code": "STAMEN_CENTERING", "ai_verdict": "pass", "human_final_verdict": "fail"}],
        )
    finally:
        session.close()

    report = client.get(f"/api/qc/probation/{probation_id}/disagreement-report").json()
    assert report["disagreements"] == 1
    assert report["detection_points"][0]["point_code"] == "STAMEN_CENTERING"
