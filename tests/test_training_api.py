"""API tests for the Digital QC Studio training step
(PRD workflow §9.5-9.8): recording CV+VLM judgments against labeled
samples, per-decision admin review, the rolling-window gate status
endpoint, and its wiring into the publish gate."""
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

from src.api.main import app
from src.api.deps import get_db_dep
from src.qc_model.studio import ai_gateway


@pytest.fixture()
def db_session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
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
            struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def _create_and_confirm(client) -> str:
    resp = client.post(
        "/admin/studio/chat",
        json={"tenant_id": "default", "message": "create sku TRAIN-API-001 Test widget"},
    )
    sku_id = resp.json()["sku"]["id"]
    card = client.post(
        "/admin/studio/chat",
        json={"message": "petal integrity", "sku_id": sku_id},
    ).json()["confirmation_card"]
    client.post(
        "/admin/studio/confirm",
        json={"intake_id": card["intake_id"], "confirmed_by": "admin", "checkpoints": card["checkpoints"]},
    )
    uploaded = client.post(
        f"/admin/samples/{sku_id}/photos",
        data={"tenant_id": "default", "is_primary": "true", "view_type": "standard", "capture_source": "usb_camera"},
        files={"photo_file": ("standard.png", _tiny_png(), "image/png")},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303, uploaded.text
    return sku_id


def _add_training_photo(client, sku_id) -> str:
    before = {
        photo["id"] for photo in client.get(f"/admin/studio/skus/{sku_id}").json()["photos"]
    }
    uploaded = client.post(
        f"/admin/samples/{sku_id}/photos",
        data={"tenant_id": "default", "is_primary": "false", "view_type": "training_instance", "capture_source": "usb_camera"},
        files={"photo_file": ("training-instance.png", _tiny_png(), "image/png")},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303, uploaded.text
    after = client.get(f"/admin/studio/skus/{sku_id}").json()["photos"]
    added = [photo["id"] for photo in after if photo["id"] not in before]
    assert len(added) == 1
    return added[0]


def _submit_judgment(client, monkeypatch, sku_id, *, ground_truth_label, model_result="pass"):
    def fake_inspect_image(**kwargs):
        return {
            "summary": "reviewed",
            "checkpoint_results": [
                {
                    "point_code": item["point_code"], "result": model_result, "confidence": 0.9,
                    "observed_value": "clean" if model_result == "pass" else "damaged",
                    "notes": "auto",
                }
                for item in kwargs["checkpoints"]
            ],
            "assistant": {
                "role": "vision", "provider": "openai_compatible", "model": "local-4b",
                "elapsed_ms": 90, "mode": "live",
            },
        }

    monkeypatch.setattr(ai_gateway, "inspect_image", fake_inspect_image)
    sample_photo_id = _add_training_photo(client, sku_id)
    resp = client.post(
        f"/admin/studio/skus/{sku_id}/training/judgments",
        data={
            "tenant_id": "default",
            "ground_truth_label": ground_truth_label,
            "sample_photo_id": sample_photo_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["judgment"]


def test_record_judgment_requires_active_revision(client):
    resp = client.post(
        "/admin/studio/chat",
        json={"tenant_id": "default", "message": "create sku TRAIN-API-002 No standard yet"},
    )
    sku_id = resp.json()["sku"]["id"]
    resp = client.post(
        f"/admin/studio/skus/{sku_id}/training/judgments",
        data={
            "tenant_id": "default",
            "ground_truth_label": "qualified",
            "sample_photo_id": "not-created",
        },
    )
    assert resp.status_code == 400
    assert "active confirmed standard" in resp.json()["error"]


def test_record_judgment_rejects_invalid_ground_truth_label(client):
    sku_id = _create_and_confirm(client)
    sample_photo_id = _add_training_photo(client, sku_id)
    resp = client.post(
        f"/admin/studio/skus/{sku_id}/training/judgments",
        data={
            "tenant_id": "default",
            "ground_truth_label": "maybe",
            "sample_photo_id": sample_photo_id,
        },
    )
    assert resp.status_code == 400
    assert "ground_truth_label" in resp.json()["error"]


def test_record_and_review_judgment_full_round_trip(client, monkeypatch):
    sku_id = _create_and_confirm(client)
    judgment = _submit_judgment(client, monkeypatch, sku_id, ground_truth_label="qualified")
    assert judgment["status"] == "awaiting_admin_review"
    assert judgment["model_overall_result"] == "pass"

    pending = client.get(f"/admin/studio/skus/{sku_id}/training/judgments").json()["judgments"]
    assert len(pending) == 1
    assert pending[0]["id"] == judgment["id"]

    decision = client.post(
        f"/admin/studio/training/judgments/{judgment['id']}/decision",
        json={"tenant_id": "default", "admin_id": "admin-1", "decision": "correct"},
    )
    assert decision.status_code == 200, decision.text
    assert decision.json()["judgment"]["status"] == "reviewed"

    pending_after = client.get(f"/admin/studio/skus/{sku_id}/training/judgments").json()["judgments"]
    assert pending_after == []


def test_decision_append_only_via_api(client, monkeypatch):
    sku_id = _create_and_confirm(client)
    judgment = _submit_judgment(client, monkeypatch, sku_id, ground_truth_label="qualified")
    client.post(
        f"/admin/studio/training/judgments/{judgment['id']}/decision",
        json={"tenant_id": "default", "admin_id": "admin-1", "decision": "correct"},
    )
    second = client.post(
        f"/admin/studio/training/judgments/{judgment['id']}/decision",
        json={"tenant_id": "default", "admin_id": "admin-2", "decision": "incorrect",
              "correction": {"point_code": "X", "model_error": "y", "correct_conclusion": "z", "correct_facts": "w"}},
    )
    assert second.status_code == 400
    assert "already reviewed" in second.json()["error"]


def test_decision_incorrect_requires_correction_fields(client, monkeypatch):
    sku_id = _create_and_confirm(client)
    judgment = _submit_judgment(client, monkeypatch, sku_id, ground_truth_label="unqualified", model_result="fail")
    resp = client.post(
        f"/admin/studio/training/judgments/{judgment['id']}/decision",
        json={"tenant_id": "default", "admin_id": "admin-1", "decision": "incorrect"},
    )
    assert resp.status_code == 400
    assert "correction" in resp.json()["error"]


def test_training_status_reflects_reviewed_judgments_and_gates_publish(client, monkeypatch):
    sku_id = _create_and_confirm(client)

    status_empty = client.get(f"/admin/studio/skus/{sku_id}/training/status").json()
    assert status_empty["status"]["qualified"] is False
    assert status_empty["status"]["total_reviewed"] == 0

    # Publish must be refused before the training window qualifies.
    refused = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert refused.status_code == 400
    assert "training" in refused.json()["error"].lower()

    for i in range(29):
        label = "qualified" if i % 2 == 0 else "unqualified"
        result = "pass" if i % 2 == 0 else "fail"
        judgment = _submit_judgment(client, monkeypatch, sku_id, ground_truth_label=label, model_result=result)
        decision = client.post(
            f"/admin/studio/training/judgments/{judgment['id']}/decision",
            json={"tenant_id": "default", "admin_id": "admin-1", "decision": "correct"},
        )
        assert decision.status_code == 200, decision.text

    status_29 = client.get(f"/admin/studio/skus/{sku_id}/training/status").json()
    assert status_29["status"]["qualified"] is False
    assert status_29["status"]["total_reviewed"] == 29

    judgment = _submit_judgment(
        client, monkeypatch, sku_id, ground_truth_label="unqualified", model_result="fail"
    )
    decision = client.post(
        f"/admin/studio/training/judgments/{judgment['id']}/decision",
        json={"tenant_id": "default", "admin_id": "admin-1", "decision": "correct"},
    )
    assert decision.status_code == 200, decision.text

    status_full = client.get(f"/admin/studio/skus/{sku_id}/training/status").json()
    assert status_full["status"]["qualified"] is True
    assert status_full["status"]["total_reviewed"] == 30

    published = client.post("/admin/studio/publish", json={"sku_id": sku_id})
    assert published.status_code == 200, published.text
