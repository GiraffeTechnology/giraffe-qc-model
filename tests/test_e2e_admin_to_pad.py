"""S7 — Admin → Pad → Server end-to-end integration (§15 DoD flow, §16.3, §16.4).

This is the cross-session integration proof: a single tenant + SKU is threaded
through the surfaces that three independently-built sessions own, asserting that
what one session persists is what the next one consumes.

    S2 Admin Studio      create SKU → upload standard photo → extract QC
    (qc_studio_router)   requirements → confirm → active standard revision +
                         detection points → publish signed L2 bundle
              │  (SKU id + standard_revision_id + detection-point codes)
              ▼
    S3 Bundle / Pad      record a signed bundle → register a (simulated)
    (qc_bundle_router)   workstation → assign the bundle → the Pad reports the
                         installed version back
              │  (standard_revision_id + bundle_version the Pad actually ran)
              ▼
    S4 Server verdict    the Pad submits its result → the server recomputes the
    (qc_verdict_router)  authoritative verdict against that exact revision,
                         never trusting the Pad → Admin Results shows both

The verdict recompute reads the *same* ``QCSkuStandardRevision`` /
``QCDetectionPoint`` rows the Studio confirmation wrote, so the chain is a real
data hand-off, not three isolated fixtures. Bundle signing/verification and the
studio photo-serving route stay fail-closed throughout.

The Pad's own on-device flow (camera, MNN inference, offline SQLite selection)
is exercised by the Android JVM unit suite in ``apps/android-qc`` under the
``android-pad-ci`` workflow; here the Pad is represented by its server-facing
API calls (upload, workstation report, result submission) — i.e. simulated,
never hardware-verified.
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
import src.db.sku_models          # noqa: F401 — register tables
import src.db.execution_models    # noqa: F401
import src.db.intake_models       # noqa: F401
import src.db.studio_models       # noqa: F401
import src.db.qc_bundle_models    # noqa: F401
import src.db.qc_verdict_models   # noqa: F401
import src.db.training_models     # noqa: F401

from src.api.main import app
from src.api.deps import get_db_dep
from src.qc_model.bundle import manifest as bundle_manifest
from src.qc_model.studio.service import verify_bundle as verify_studio_bundle


TENANT = "tenant_acme"
BUNDLE_VERSION = "1.0.0"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def db_session_factory():
    # Bundle signing is Ed25519 (canonical, no HMAC secret); under APP_ENV=test
    # the signer uses an ephemeral per-process keypair, so no env is needed.
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
        c.headers.update({"X-QC-Mutation-Key": "sample-mutation-test-key", "X-QC-Sample-Surface": "sample-standard"})
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


# ── S2 helpers ─────────────────────────────────────────────────────────────────


def _studio_create_confirm(client) -> dict:
    """Walk the Studio DoD steps; return {sku_id, revision_id, point_codes, photo_url}."""
    # 1. Create SKU FLW-001 via chat, under the non-default tenant.
    created = client.post(
        "/admin/studio/chat",
        json={"tenant_id": TENANT, "message": "create sku FLW-001 Flower Brooch"},
    ).json()
    assert created["action"] == "created_sku", created
    sku_id = created["sku"]["id"]

    # 2. Upload a standard photo (S2 hardened upload).
    up = client.post(
        "/admin/samples/upload",
        data={"sku_id": sku_id, "tenant_id": TENANT},
        files={"image": ("std.png", _tiny_png(), "image/png")},
    )
    assert up.status_code == 200, up.text
    photo_url = up.json()["url"]

    # 3. Describe the QC requirements with explicit counts → clean extraction.
    card = client.post(
        "/admin/studio/chat",
        json={"message": "pearl count 3, rhinestone count 8", "sku_id": sku_id,
              "tenant_id": TENANT},
    ).json()["confirmation_card"]

    # 4. Confirm → persists the active standard revision + detection points.
    confirmed = client.post(
        "/admin/studio/confirm",
        json={
            "tenant_id": TENANT,
            "intake_id": card["intake_id"],
            "confirmed_by": "admin",
            "checkpoints": card["checkpoints"],
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["sku"]["standard_status"] == "standard_active"
    revision_id = body["revision_id"]

    # The detection-point codes the server must later require of the Pad.
    point_codes = [dp["point_code"] for dp in body["sku"]["detection_points"]]
    assert point_codes, "confirmation must yield at least one detection point"

    return {
        "sku_id": sku_id,
        "revision_id": revision_id,
        "point_codes": point_codes,
        "photo_url": photo_url,
    }


def _s3_signed_bundle_body(sku_id: str, revision_id: str) -> dict:
    signed = bundle_manifest.create_signed_bundle(
        bundle_version=BUNDLE_VERSION,
        tenant_id=TENANT,
        skus=[{
            "sku_id": sku_id,
            "item_number": "FLW-001",
            "standard_revision_id": revision_id,
            "revision_no": 1,
        }],
        photos=[{"photo_id": "p1", "sku_id": sku_id,
                 "sha256": "a" * 64, "path": "photos/p1.jpg"}],
        created_by="studio@acme",
    )
    return {
        "tenant_id": TENANT,
        "manifest": signed.manifest,
        "signature": signed.signature,
        "signature_algo": signed.signature_algo,
        "manifest_sha256": signed.manifest_sha256,
        "created_by": "studio@acme",
    }


# ── The single required Definition-of-Done demo (§15) ─────────────────────────


def _qualify_training(db_session_factory, sku_id: str, standard_revision_id: str, tenant_id: str = TENANT) -> None:
    """Directly insert a qualifying rolling window of reviewed training
    judgments (PRD §9.5-9.8) so this cross-session e2e proof stays focused
    on the Admin -> Pad -> Server hand-off it exists to test, rather than
    also mocking 29 individual CV+VLM training calls -- the training gate's
    own logic is exhaustively covered by tests/test_training_gate.py."""
    import uuid
    from datetime import datetime, timedelta, timezone

    from src.db.training_models import QCTrainingJudgment

    session = db_session_factory()
    try:
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for i in range(30):
            session.add(QCTrainingJudgment(
                id=uuid.uuid4().hex, tenant_id=tenant_id, sku_id=sku_id,
                standard_revision_id=standard_revision_id,
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


def test_admin_to_pad_e2e_definition_of_done(client, db_session_factory):
    ctx = _studio_create_confirm(client)
    sku_id, revision_id, point_codes = ctx["sku_id"], ctx["revision_id"], ctx["point_codes"]

    # S2: the right-panel preview URL is tenant-aware and resolves (200, not 404).
    assert f"tenant_id={TENANT}" in ctx["photo_url"]
    assert client.get(ctx["photo_url"]).status_code == 200

    # S2: publish a signed L2 studio bundle over the confirmed standard.
    _qualify_training(db_session_factory, sku_id, revision_id)
    pub = client.post("/admin/studio/publish", json={"tenant_id": TENANT, "sku_id": sku_id})
    assert pub.status_code == 200, pub.text
    bundle = pub.json()["bundle"]
    assert bundle["detection_point_count"] == len(point_codes)

    # S3: record a signed bundle, register a simulated workstation, assign it,
    # and have the Pad report the installed version back.
    rec = client.post("/api/qc/bundles", json=_s3_signed_bundle_body(sku_id, revision_id))
    assert rec.status_code == 201, rec.text
    bundle_pk = rec.json()["id"]

    ws = client.post("/api/qc/workstations", json={
        "tenant_id": TENANT, "workstation_id": "ws-line-1",
        "display_name": "Line 1", "site_or_line": "Line 1",
    })
    assert ws.status_code == 201, ws.text
    ws_pk = ws.json()["id"]

    assigned = client.post(
        f"/api/qc/workstations/{ws_pk}/assign",
        json={"tenant_id": TENANT, "bundle_pk": bundle_pk, "assigned_by": "admin"},
    )
    assert assigned.status_code == 201, assigned.text
    assert assigned.json()["assigned_bundle_version"] == BUNDLE_VERSION

    reported = client.post(
        f"/api/qc/workstations/{ws_pk}/report",
        json={"tenant_id": TENANT, "installed_bundle_version": BUNDLE_VERSION,
              "sync_status": "ok"},
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["installed_bundle_version"] == BUNDLE_VERSION
    assert reported.json()["in_sync"] is True

    # S4: the Pad submits a clean PASS result carrying the exact revision +
    # bundle version it ran. The server recomputes and agrees.
    submission = client.post("/api/qc/results/submissions", json={
        "tenant_id": TENANT,
        "job_ref": "job-e2e-1",
        "standard_revision_id": revision_id,
        "bundle_version": BUNDLE_VERSION,
        "pad_overall_result": "pass",
        "workstation_id": "ws-line-1",
        "checkpoints": [{"checkpoint_id": pc, "result": "pass"} for pc in point_codes],
    })
    assert submission.status_code == 201, submission.text
    verdict = submission.json()
    assert verdict["server_overall_result"] == "pass"
    assert verdict["agrees"] is True
    assert verdict["standard_revision_id"] == revision_id

    # The Admin Results page shows the server-recomputed verdict for this tenant.
    page = client.get("/admin/results", params={"tenant_id": TENANT})
    assert page.status_code == 200
    assert "Server Verdict" in page.text


# ── §16.4 fail-closed guarantees along the same chain ─────────────────────────


def test_e2e_pad_claimed_pass_is_overridden_on_failed_checkpoint(client):
    """Safety-critical: the server never lets a Pad-claimed PASS stand over a fail."""
    ctx = _studio_create_confirm(client)
    point_codes = ctx["point_codes"]

    # Pad claims PASS but one checkpoint actually failed.
    checkpoints = [{"checkpoint_id": pc, "result": "pass"} for pc in point_codes]
    checkpoints[0]["result"] = "fail"

    verdict = client.post("/api/qc/results/submissions", json={
        "tenant_id": TENANT,
        "job_ref": "job-e2e-fail",
        "standard_revision_id": ctx["revision_id"],
        "bundle_version": BUNDLE_VERSION,
        "pad_overall_result": "pass",
        "checkpoints": checkpoints,
    }).json()

    assert verdict["server_overall_result"] == "fail"
    assert verdict["agrees"] is False
    assert "pad_claimed_pass_overridden" in verdict["warnings"]


def test_e2e_pad_claimed_pass_with_missing_checkpoint_is_not_pass(client):
    """A PASS that omits a required checkpoint is recomputed non-pass."""
    ctx = _studio_create_confirm(client)
    point_codes = ctx["point_codes"]
    assert len(point_codes) >= 2

    # Submit only the first required checkpoint → the rest are missing.
    verdict = client.post("/api/qc/results/submissions", json={
        "tenant_id": TENANT,
        "job_ref": "job-e2e-missing",
        "standard_revision_id": ctx["revision_id"],
        "bundle_version": BUNDLE_VERSION,
        "pad_overall_result": "pass",
        "checkpoints": [{"checkpoint_id": point_codes[0], "result": "pass"}],
    }).json()

    assert verdict["server_overall_result"] != "pass"
    assert "pad_claimed_pass_overridden" in verdict["warnings"]


def test_e2e_unknown_revision_fails_closed(client):
    """An unknown standard_revision_id fails closed to review_required."""
    _studio_create_confirm(client)  # a real revision exists, but we cite a bogus one
    verdict = client.post("/api/qc/results/submissions", json={
        "tenant_id": TENANT,
        "job_ref": "job-e2e-unknown",
        "standard_revision_id": "does-not-exist",
        "bundle_version": BUNDLE_VERSION,
        "pad_overall_result": "pass",
        "checkpoints": [{"checkpoint_id": "PEARL_COUNT", "result": "pass"}],
    }).json()
    assert verdict["server_overall_result"] == "review_required"


def test_e2e_tampered_bundle_signature_rejected(client):
    """S3 re-verifies signed bundles fail-closed on ingest."""
    ctx = _studio_create_confirm(client)
    body = _s3_signed_bundle_body(ctx["sku_id"], ctx["revision_id"])
    # Deterministically flip the first character so the signature is *always*
    # changed, regardless of what the signer produced this run (the manifest
    # timestamp varies run to run). "0" and "1" are both valid base64 chars, so
    # the length and alphabet stay valid — only the value differs, and Ed25519
    # verification fails closed.
    sig = body["signature"]
    body["signature"] = ("1" if sig[0] == "0" else "0") + sig[1:]  # tamper
    rec = client.post("/api/qc/bundles", json=body)
    assert rec.status_code == 400


def test_e2e_studio_photo_isolated_across_tenants(client):
    """A photo owned by tenant_acme must not resolve under another tenant."""
    ctx = _studio_create_confirm(client)
    # Correct tenant → 200.
    assert client.get(ctx["photo_url"]).status_code == 200
    # Wrong tenant / route default → 404 (fail-closed isolation).
    base = ctx["photo_url"].split("?")[0]
    assert client.get(base).status_code == 404
    assert client.get(base, params={"tenant_id": "someone_else"}).status_code == 404


def test_e2e_studio_upload_rejects_non_image(client):
    """The Studio upload path rejects a non-image masquerading as PNG (MIME sniff)."""
    created = client.post(
        "/admin/studio/chat",
        json={"tenant_id": TENANT, "message": "create sku FLW-001 Flower Brooch"},
    ).json()
    sku_id = created["sku"]["id"]
    resp = client.post(
        "/admin/samples/upload",
        data={"sku_id": sku_id, "tenant_id": TENANT},
        files={"image": ("evil.png", b"#!/bin/sh\nrm -rf /", "image/png")},
    )
    assert resp.status_code == 415
