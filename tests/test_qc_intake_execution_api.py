"""Tests for the QC Standard Intake and Inspection Execution APIs.

Covers:
1.  POST /api/v1/qc/intakes → creates intake with status 'received'
2.  POST /api/v1/qc/intakes/{id}/extract → status 'pending_confirmation', checkpoints extracted
3.  POST /api/v1/qc/intakes/{id}/confirm → active revision created, checkpoint_count correct
4.  POST /api/v1/qc/intakes/{id}/reject → status 'rejected'
5.  Extraction: FLOWER-BROOCH-001 raw text → PEARL_COUNT, RHINESTONE_COUNT, STAMEN_CENTERING, PETAL_INTEGRITY
6.  Extraction: SHIRT-CUSTOM-001 raw text → BUTTON_COUNT, COLLAR_STITCHING, FABRIC_STAIN, LABEL_POSITION
7.  Extraction: METAL-BRACKET-001 raw text → HOLE_COUNT, SURFACE_SCRATCH, EDGE_BURR, DEFORMATION_CHECK
8.  Extraction: CARTON-LABEL-001 raw text → BARCODE_PRESENT, BARCODE_READABLE, CARTON_DAMAGE, SEAL_INTEGRITY
9.  POST /api/v1/qc/inspection-jobs → creates job, snapshots active revision
10. POST /api/v1/qc/inspection-jobs/{id}/model-results → checkpoint results + findings persisted
11. POST /api/v1/qc/inspection-jobs/{id}/finalize → report with correct overall_result
12. POST /api/v1/qc/inspection-jobs/{id}/model-results with unknown point_code → 400
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_models          # noqa: F401
import src.db.sku_models         # noqa: F401
import src.db.execution_models   # noqa: F401
import src.db.intake_models      # noqa: F401

from src.api.main import app
from src.api.deps import get_db_dep
from src.db.seed_data import (
    seed_flower_brooch,
    seed_shirt_custom,
    seed_metal_bracket,
    seed_carton_label,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def db_session_factory(db_engine):
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
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


@pytest.fixture(scope="module")
def seeded_skus(db_session_factory):
    """Seed all four test SKUs once per module; return a mapping of item_number → sku_id string."""
    session = db_session_factory()
    try:
        brooch = seed_flower_brooch(session, tenant_id="default")
        shirt = seed_shirt_custom(session, tenant_id="default")
        bracket = seed_metal_bracket(session, tenant_id="default")
        carton = seed_carton_label(session, tenant_id="default")
        return {
            "FLOWER-BROOCH-001": brooch.id,
            "SHIRT-CUSTOM-001": shirt.id,
            "METAL-BRACKET-001": bracket.id,
            "CARTON-LABEL-001": carton.id,
        }
    finally:
        session.close()


# ── Test 1: Create intake ─────────────────────────────────────────────────────


def test_create_intake_returns_received_status(client, seeded_skus):
    sku_id = seeded_skus["FLOWER-BROOCH-001"]
    resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": "Pearl count 3, rhinestone count 8, stamen centering, petal integrity.",
            "source_type": "api",
            "operator_id": "op-alice",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "received"
    assert body["sku_id"] == sku_id
    assert body["tenant_id"] == "default"


# ── Test 2: Extract draft ─────────────────────────────────────────────────────


def test_extract_draft_produces_pending_confirmation(client, seeded_skus):
    sku_id = seeded_skus["FLOWER-BROOCH-001"]
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": "Pearl count 3, rhinestone count 8, petal integrity check.",
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    extract_resp = client.post(f"/api/v1/qc/intakes/{intake_id}/extract")
    assert extract_resp.status_code == 200, extract_resp.text
    body = extract_resp.json()
    assert body["status"] == "pending_confirmation"
    assert body["extracted_json"] is not None
    extracted = body["extracted_json"]
    codes = {cp["point_code"] for cp in extracted["checkpoints"]}
    assert "PEARL_COUNT" in codes
    assert "RHINESTONE_COUNT" in codes
    assert "PETAL_INTEGRITY" in codes


# ── Test 3: Confirm intake ────────────────────────────────────────────────────


def test_confirm_intake_creates_active_revision(client, seeded_skus):
    sku_id = seeded_skus["SHIRT-CUSTOM-001"]
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": "Button count 7, collar stitching, fabric stain check, label position.",
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    client.post(f"/api/v1/qc/intakes/{intake_id}/extract")

    confirm_resp = client.post(
        f"/api/v1/qc/intakes/{intake_id}/confirm",
        json={
            "confirmed_by": "alice",
            "checkpoints": [
                {"point_code": "BUTTON_COUNT", "label": "Button Count",
                 "severity": "critical", "expected_value": "7", "method_hint": "counting"},
                {"point_code": "COLLAR_STITCHING", "label": "Collar Stitching",
                 "severity": "major", "method_hint": "defect_detection"},
                {"point_code": "FABRIC_STAIN", "label": "Fabric Stain",
                 "severity": "major", "method_hint": "defect_detection"},
                {"point_code": "LABEL_POSITION", "label": "Label Position",
                 "severity": "minor", "method_hint": "alignment"},
            ],
        },
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    body = confirm_resp.json()
    assert body["status"] == "active"
    assert body["confirmed_by"] == "alice"
    assert body["checkpoint_count"] == 4


# ── Test 4: Reject intake ─────────────────────────────────────────────────────


def test_reject_intake_sets_rejected_status(client, seeded_skus):
    sku_id = seeded_skus["METAL-BRACKET-001"]
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": "Hole count 4, surface scratch, edge burr, deformation check.",
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    reject_resp = client.post(
        f"/api/v1/qc/intakes/{intake_id}/reject",
        json={"rejected_by": "bob", "reason": "Incorrect product specification."},
    )
    assert reject_resp.status_code == 200, reject_resp.text
    body = reject_resp.json()
    assert body["status"] == "rejected"


# ── Tests 5–8: Multi-SKU extraction ──────────────────────────────────────────


def test_flower_brooch_extraction_extracts_correct_checkpoints(client, seeded_skus):
    sku_id = seeded_skus["FLOWER-BROOCH-001"]
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": (
                "Pearl count 3 around stamen. Rhinestone count 8 in outer ring. "
                "Stamen centering within 2mm. Petal integrity — no cracks."
            ),
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    extract_resp = client.post(f"/api/v1/qc/intakes/{intake_id}/extract")
    assert extract_resp.status_code == 200
    codes = {
        cp["point_code"]
        for cp in extract_resp.json()["extracted_json"]["checkpoints"]
    }
    assert {"PEARL_COUNT", "RHINESTONE_COUNT", "STAMEN_CENTERING", "PETAL_INTEGRITY"} <= codes


def test_shirt_extraction_extracts_correct_checkpoints(client, seeded_skus):
    sku_id = seeded_skus["SHIRT-CUSTOM-001"]
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": (
                "Button count 7. Collar stitching must be even. "
                "Fabric stain — no visible marks. Label position at inner back collar."
            ),
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    extract_resp = client.post(f"/api/v1/qc/intakes/{intake_id}/extract")
    assert extract_resp.status_code == 200
    codes = {
        cp["point_code"]
        for cp in extract_resp.json()["extracted_json"]["checkpoints"]
    }
    assert {"BUTTON_COUNT", "COLLAR_STITCHING", "FABRIC_STAIN", "LABEL_POSITION"} <= codes


def test_metal_bracket_extraction_extracts_correct_checkpoints(client, seeded_skus):
    sku_id = seeded_skus["METAL-BRACKET-001"]
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": (
                "Hole count 4 mounting holes. Surface scratch check. "
                "Edge burr removal. Deformation check against template."
            ),
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    extract_resp = client.post(f"/api/v1/qc/intakes/{intake_id}/extract")
    assert extract_resp.status_code == 200
    codes = {
        cp["point_code"]
        for cp in extract_resp.json()["extracted_json"]["checkpoints"]
    }
    assert {"HOLE_COUNT", "SURFACE_SCRATCH", "EDGE_BURR", "DEFORMATION_CHECK"} <= codes


def test_carton_label_extraction_extracts_correct_checkpoints(client, seeded_skus):
    sku_id = seeded_skus["CARTON-LABEL-001"]
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": (
                "Barcode present on carton. Barcode readable — must scan correctly. "
                "Carton damage check. Seal integrity — all seals unbroken."
            ),
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    extract_resp = client.post(f"/api/v1/qc/intakes/{intake_id}/extract")
    assert extract_resp.status_code == 200
    codes = {
        cp["point_code"]
        for cp in extract_resp.json()["extracted_json"]["checkpoints"]
    }
    assert {"BARCODE_PRESENT", "BARCODE_READABLE", "CARTON_DAMAGE", "SEAL_INTEGRITY"} <= codes


# ── Test 9: Create inspection job ────────────────────────────────────────────


def test_create_inspection_job_snapshots_active_revision(client, seeded_skus):
    sku_id = seeded_skus["FLOWER-BROOCH-001"]
    resp = client.post(
        "/api/v1/qc/inspection-jobs",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "job_ref": "JOB-API-001",
            "created_by": "alice",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["sku_id"] == sku_id
    assert body["status"] == "pending"
    assert body["active_standard_revision_id"] is not None

    # GET the job
    get_resp = client.get(f"/api/v1/qc/inspection-jobs/{body['id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == body["id"]


# ── Test 10: Ingest model output ─────────────────────────────────────────────


def test_ingest_model_output_creates_checkpoint_results(client, seeded_skus):
    sku_id = seeded_skus["FLOWER-BROOCH-001"]
    job_resp = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": "default", "sku_id": sku_id, "job_ref": "JOB-API-MODEL"},
    )
    assert job_resp.status_code == 201
    job_id = job_resp.json()["id"]

    model_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "STAMEN_CENTERING", "result": "pass", "confidence": 0.95},
                    {"point_code": "PEARL_COUNT", "result": "pass", "observed_value": "3", "confidence": 0.99},
                    {"point_code": "RHINESTONE_COUNT", "result": "pass", "observed_value": "8", "confidence": 0.98},
                    {"point_code": "PETAL_INTEGRITY", "result": "pass", "confidence": 0.97},
                ],
                "incidental_findings": [
                    {"severity": "minor", "description": "Slight dust on back petal edge."},
                ],
            },
        },
    )
    assert model_resp.status_code == 201, model_resp.text
    body = model_resp.json()
    assert body["job_id"] == job_id
    assert "id" in body


# ── Test 11: Finalize inspection job ─────────────────────────────────────────


def test_finalize_inspection_job_produces_pass_report(client, seeded_skus):
    sku_id = seeded_skus["METAL-BRACKET-001"]
    job_resp = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": "default", "sku_id": sku_id, "job_ref": "JOB-API-FINALIZE"},
    )
    assert job_resp.status_code == 201
    job_id = job_resp.json()["id"]

    client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "HOLE_COUNT", "result": "pass", "observed_value": "4"},
                    {"point_code": "SURFACE_SCRATCH", "result": "pass"},
                    {"point_code": "EDGE_BURR", "result": "pass"},
                    {"point_code": "DEFORMATION_CHECK", "result": "pass"},
                ],
                "incidental_findings": [],
            },
        },
    )

    finalize_resp = client.post(f"/api/v1/qc/inspection-jobs/{job_id}/finalize")
    assert finalize_resp.status_code == 200, finalize_resp.text
    body = finalize_resp.json()
    assert body["overall_result"] == "pass"
    assert body["checkpoint_results_count"] == 4
    assert body["findings_count"] == 0

    # GET report
    report_resp = client.get(f"/api/v1/qc/inspection-jobs/{job_id}/report")
    assert report_resp.status_code == 200
    assert report_resp.json()["overall_result"] == "pass"


# ── Test 12: Unknown point_code → 400 ────────────────────────────────────────


def test_ingest_model_output_rejects_unknown_point_code(client, seeded_skus):
    sku_id = seeded_skus["CARTON-LABEL-001"]
    job_resp = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": "default", "sku_id": sku_id, "job_ref": "JOB-API-BAD"},
    )
    assert job_resp.status_code == 201
    job_id = job_resp.json()["id"]

    model_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "NONEXISTENT_CHECKPOINT", "result": "pass"},
                ],
                "incidental_findings": [],
            },
        },
    )
    assert model_resp.status_code == 400, model_resp.text
    assert "NONEXISTENT_CHECKPOINT" in model_resp.json()["detail"]


# ── New tests (13–28) ──────────────────────────────────────────────────────────

# Helper: FLOWER-BROOCH-001 complete model output (all 4 checkpoints pass)
_BROOCH_FULL_PASS = {
    "checkpoint_results": [
        {"point_code": "STAMEN_CENTERING", "result": "pass", "confidence": 0.95},
        {"point_code": "PEARL_COUNT", "result": "pass", "observed_value": "3", "confidence": 0.99},
        {"point_code": "RHINESTONE_COUNT", "result": "pass", "observed_value": "8", "confidence": 0.98},
        {"point_code": "PETAL_INTEGRITY", "result": "pass", "confidence": 0.97},
    ],
    "incidental_findings": [],
}


def _create_brooch_job(client, seeded_skus, job_ref=None):
    """Helper: create a fresh inspection job for FLOWER-BROOCH-001."""
    sku_id = seeded_skus["FLOWER-BROOCH-001"]
    resp = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": "default", "sku_id": sku_id, "job_ref": job_ref},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# 13
def test_create_standard_intake_from_raw_text(client, seeded_skus):
    sku_id = seeded_skus["FLOWER-BROOCH-001"]
    resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": "Pearl count 3, rhinestone count 8, stamen centering.",
            "source_type": "api",
            "operator_id": "op-test13",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "received"
    assert body["sku_id"] == sku_id
    assert body["tenant_id"] == "default"


# 14
def test_extract_standard_draft_from_intake(client, seeded_skus):
    sku_id = seeded_skus["FLOWER-BROOCH-001"]
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": "Stamen centering, petal integrity.",
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    extract_resp = client.post(f"/api/v1/qc/intakes/{intake_id}/extract")
    assert extract_resp.status_code == 200, extract_resp.text
    body = extract_resp.json()
    assert body["status"] == "pending_confirmation"
    assert body["extracted_json"] is not None


# 15
def test_confirm_intake_creates_active_standard_revision(client, seeded_skus):
    sku_id = seeded_skus["METAL-BRACKET-001"]
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": "Hole count 4, surface scratch, edge burr, deformation check.",
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    client.post(f"/api/v1/qc/intakes/{intake_id}/extract")

    confirm_resp = client.post(
        f"/api/v1/qc/intakes/{intake_id}/confirm",
        json={
            "confirmed_by": "op-test15",
            "checkpoints": [
                {"point_code": "HOLE_COUNT", "label": "Hole Count", "severity": "critical"},
                {"point_code": "SURFACE_SCRATCH", "label": "Surface Scratch", "severity": "major"},
                {"point_code": "EDGE_BURR", "label": "Edge Burr", "severity": "major"},
                {"point_code": "DEFORMATION_CHECK", "label": "Deformation Check", "severity": "critical"},
            ],
        },
    )
    assert confirm_resp.status_code == 200, confirm_resp.text
    body = confirm_resp.json()
    assert body["status"] == "active"
    assert body["checkpoint_count"] >= 1


# 16
def test_confirm_intake_rejects_duplicate_checkpoint_codes(client, seeded_skus):
    sku_id = seeded_skus["SHIRT-CUSTOM-001"]
    # Create a fresh intake for SHIRT-CUSTOM-001 (has BUTTON_COUNT in its seed)
    create_resp = client.post(
        "/api/v1/qc/intakes",
        json={
            "tenant_id": "default",
            "sku_id": sku_id,
            "raw_text": "Button count 7, collar stitching.",
        },
    )
    assert create_resp.status_code == 201
    intake_id = create_resp.json()["id"]

    client.post(f"/api/v1/qc/intakes/{intake_id}/extract")

    # Count existing revisions for this SKU before the bad confirm
    from src.db.sku_models import QCSkuStandardRevision
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    # Submit confirm with duplicate normalized codes: "button_count" and "BUTTON_COUNT"
    confirm_resp = client.post(
        f"/api/v1/qc/intakes/{intake_id}/confirm",
        json={
            "confirmed_by": "op-test16",
            "checkpoints": [
                {"point_code": "button_count", "label": "Button Count A", "severity": "critical"},
                {"point_code": "BUTTON_COUNT", "label": "Button Count B", "severity": "critical"},
            ],
        },
    )
    assert confirm_resp.status_code == 400, confirm_resp.text
    assert "BUTTON_COUNT" in confirm_resp.json()["detail"]


# 17
def test_inspection_job_reuses_active_standard_without_reconfirmation(client, seeded_skus):
    sku_id = seeded_skus["FLOWER-BROOCH-001"]
    job_resp1 = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": "default", "sku_id": sku_id, "job_ref": "JOB-REUSE-A"},
    )
    job_resp2 = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": "default", "sku_id": sku_id, "job_ref": "JOB-REUSE-B"},
    )
    assert job_resp1.status_code == 201, job_resp1.text
    assert job_resp2.status_code == 201, job_resp2.text
    rev1 = job_resp1.json()["active_standard_revision_id"]
    rev2 = job_resp2.json()["active_standard_revision_id"]
    assert rev1 == rev2


# 18
def test_model_output_creates_checkpoint_results(client, seeded_skus):
    job_id = _create_brooch_job(client, seeded_skus, job_ref="JOB-TEST18")
    model_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "STAMEN_CENTERING", "result": "pass", "confidence": 0.95},
                ],
                "incidental_findings": [],
            },
        },
    )
    assert model_resp.status_code == 201, model_resp.text
    assert model_resp.json()["job_id"] == job_id


# 19
def test_model_output_rejects_unknown_point_code(client, seeded_skus):
    job_id = _create_brooch_job(client, seeded_skus, job_ref="JOB-TEST19")
    model_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "NONEXISTENT_CODE", "result": "pass"},
                ],
                "incidental_findings": [],
            },
        },
    )
    assert model_resp.status_code == 400, model_resp.text


# 20
def test_model_output_rejects_duplicate_point_code_atomically(client, seeded_skus):
    job_id = _create_brooch_job(client, seeded_skus, job_ref="JOB-TEST20")

    # Submit with STAMEN_CENTERING appearing twice
    bad_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "STAMEN_CENTERING", "result": "pass", "confidence": 0.95},
                    {"point_code": "PEARL_COUNT", "result": "pass"},
                    {"point_code": "STAMEN_CENTERING", "result": "fail"},  # duplicate
                ],
                "incidental_findings": [],
            },
        },
    )
    assert bad_resp.status_code == 400, bad_resp.text
    detail = bad_resp.json()["detail"]
    assert "STAMEN_CENTERING" in detail or "duplicate" in detail.lower()

    # Job should still be pending (no partial commit)
    get_resp = client.get(f"/api/v1/qc/inspection-jobs/{job_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["status"] == "pending"

    # Re-submit a corrected payload (all checkpoints once, all pass) should succeed
    good_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": _BROOCH_FULL_PASS,
        },
    )
    assert good_resp.status_code == 201, good_resp.text


# 21
def test_model_output_rejects_existing_checkpoint_result_atomically(client, seeded_skus):
    job_id = _create_brooch_job(client, seeded_skus, job_ref="JOB-TEST21")

    # First valid submission (all 4 checkpoints pass)
    first_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": _BROOCH_FULL_PASS,
        },
    )
    assert first_resp.status_code == 201, first_resp.text

    # Second submission — STAMEN_CENTERING already has a result
    second_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "STAMEN_CENTERING", "result": "pass"},
                ],
                "incidental_findings": [],
            },
        },
    )
    assert second_resp.status_code == 400, second_resp.text
    detail = second_resp.json()["detail"]
    assert "STAMEN_CENTERING" in detail or "already exists" in detail.lower()


# 22
def test_model_output_rejects_wrong_media_id_atomically(client, seeded_skus):
    sku_id = seeded_skus["FLOWER-BROOCH-001"]

    # Create two jobs
    job1_resp = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": "default", "sku_id": sku_id, "job_ref": "JOB-TEST22-A"},
    )
    assert job1_resp.status_code == 201
    job1_id = job1_resp.json()["id"]

    job2_resp = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": "default", "sku_id": sku_id, "job_ref": "JOB-TEST22-B"},
    )
    assert job2_resp.status_code == 201
    job2_id = job2_resp.json()["id"]

    # Attach media to job2
    media_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job2_id}/media",
        json={"image_url": "http://example.com/img.jpg"},
    )
    assert media_resp.status_code == 201, media_resp.text
    media_id = media_resp.json()["id"]

    # Submit model output to job1 with job2's media_id — should fail
    bad_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job1_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "media_id": media_id,
            "raw_output": _BROOCH_FULL_PASS,
        },
    )
    assert bad_resp.status_code == 400, bad_resp.text
    assert "media" in bad_resp.json()["detail"].lower()

    # Re-submit without media_id — should succeed
    good_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job1_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": _BROOCH_FULL_PASS,
        },
    )
    assert good_resp.status_code == 201, good_resp.text


# 23
def test_finalize_with_missing_checkpoint_returns_review_required(client, seeded_skus):
    job_id = _create_brooch_job(client, seeded_skus, job_ref="JOB-TEST23")

    # Submit only STAMEN_CENTERING (3 checkpoints missing)
    client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "STAMEN_CENTERING", "result": "pass"},
                ],
                "incidental_findings": [],
            },
        },
    )

    finalize_resp = client.post(f"/api/v1/qc/inspection-jobs/{job_id}/finalize")
    assert finalize_resp.status_code == 200, finalize_resp.text
    assert finalize_resp.json()["overall_result"] == "review_required"


# 24
def test_finalize_with_explicit_checkpoint_fail_returns_fail(client, seeded_skus):
    job_id = _create_brooch_job(client, seeded_skus, job_ref="JOB-TEST24")

    client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "STAMEN_CENTERING", "result": "pass"},
                    {"point_code": "PEARL_COUNT", "result": "pass"},
                    {"point_code": "RHINESTONE_COUNT", "result": "pass"},
                    {"point_code": "PETAL_INTEGRITY", "result": "fail"},
                ],
                "incidental_findings": [],
            },
        },
    )

    finalize_resp = client.post(f"/api/v1/qc/inspection-jobs/{job_id}/finalize")
    assert finalize_resp.status_code == 200, finalize_resp.text
    assert finalize_resp.json()["overall_result"] == "fail"


# 25
def test_major_incidental_finding_returns_review_required(client, seeded_skus):
    job_id = _create_brooch_job(client, seeded_skus, job_ref="JOB-TEST25")

    # All 4 checkpoints pass, but one major incidental finding
    client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "STAMEN_CENTERING", "result": "pass"},
                    {"point_code": "PEARL_COUNT", "result": "pass"},
                    {"point_code": "RHINESTONE_COUNT", "result": "pass"},
                    {"point_code": "PETAL_INTEGRITY", "result": "pass"},
                ],
                "incidental_findings": [
                    {"severity": "major", "description": "Unusual coating irregularity on back face."},
                ],
            },
        },
    )

    finalize_resp = client.post(f"/api/v1/qc/inspection-jobs/{job_id}/finalize")
    assert finalize_resp.status_code == 200, finalize_resp.text
    assert finalize_resp.json()["overall_result"] == "review_required"


# 26
def test_multi_sku_seed_fixtures_have_expected_checkpoints(client, seeded_skus):
    """All four seeded SKUs must have an active revision (inspection job creation returns 201)."""
    for item_number, sku_id in seeded_skus.items():
        resp = client.post(
            "/api/v1/qc/inspection-jobs",
            json={
                "tenant_id": "default",
                "sku_id": sku_id,
                "job_ref": f"JOB-SEED-CHECK-{item_number}",
            },
        )
        assert resp.status_code == 201, f"Failed for {item_number}: {resp.text}"
        assert resp.json()["active_standard_revision_id"] is not None, (
            f"{item_number} has no active revision"
        )


# 27
def test_model_output_cannot_submit_checkpoint_from_other_sku(client, seeded_skus):
    # Create a job for CARTON-LABEL-001
    carton_sku_id = seeded_skus["CARTON-LABEL-001"]
    job_resp = client.post(
        "/api/v1/qc/inspection-jobs",
        json={"tenant_id": "default", "sku_id": carton_sku_id, "job_ref": "JOB-TEST27"},
    )
    assert job_resp.status_code == 201
    job_id = job_resp.json()["id"]

    # Submit STAMEN_CENTERING which belongs to FLOWER-BROOCH-001, not CARTON-LABEL-001
    model_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": {
                "checkpoint_results": [
                    {"point_code": "STAMEN_CENTERING", "result": "pass"},
                ],
                "incidental_findings": [],
            },
        },
    )
    assert model_resp.status_code == 400, model_resp.text


# 28
def test_finalize_api_is_idempotent(client, seeded_skus):
    job_id = _create_brooch_job(client, seeded_skus, job_ref="JOB-TEST28")

    # Submit complete model output (all 4 pass)
    model_resp = client.post(
        f"/api/v1/qc/inspection-jobs/{job_id}/model-results",
        json={
            "provider": "anthropic",
            "model_name": "claude-sonnet-4-6",
            "raw_output": _BROOCH_FULL_PASS,
        },
    )
    assert model_resp.status_code == 201, model_resp.text

    # First finalize
    finalize1 = client.post(f"/api/v1/qc/inspection-jobs/{job_id}/finalize")
    assert finalize1.status_code == 200, finalize1.text
    assert finalize1.json()["overall_result"] == "pass"

    # Second finalize — must be idempotent
    finalize2 = client.post(f"/api/v1/qc/inspection-jobs/{job_id}/finalize")
    assert finalize2.status_code == 200, finalize2.text
    assert finalize2.json()["overall_result"] == "pass"
