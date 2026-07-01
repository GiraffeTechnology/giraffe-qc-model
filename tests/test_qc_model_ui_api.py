"""Phase 1 UI + API integration tests (PRD §6, §19.4, §23.1)."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_models  # noqa: F401
import src.db.sku_models  # noqa: F401
import src.db.qc_model_models  # noqa: F401
from src.api.deps import get_db_dep
from src.api.main import app
from src.db.sku_models import QCDetectionPoint, QCSkuItem


def _uid() -> str:
    return uuid.uuid4().hex


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
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
def client(session_factory):
    def override():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db_dep] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def seeded(session_factory):
    """Seed one SKU with a visual defect and a physical-measurement DP."""
    s = session_factory()
    sku_id = _uid()
    sku = QCSkuItem(id=sku_id, tenant_id="default", item_number="FLOWER-001", name="Flower Brooch")
    s.add(sku)
    dp_visual = QCDetectionPoint(
        id=_uid(), tenant_id="default", sku_id=sku_id,
        point_code="missing_rhinestone", label="Missing rhinestone",
        description="Check whether any rhinestone is missing", severity="critical",
    )
    dp_physical = QCDetectionPoint(
        id=_uid(), tenant_id="default", sku_id=sku_id,
        point_code="chain_link_count", label="Chain link count",
        description="Verify chain link count equals expected", severity="major",
    )
    s.add(dp_visual)
    s.add(dp_physical)
    s.commit()
    ids = {"sku_id": sku_id, "visual": dp_visual.id, "physical": dp_physical.id}
    s.close()
    return ids


def test_runtime_profiles_endpoint(client):
    data = client.get("/api/qc-model/runtime-profiles").json()
    profiles = data["default_runtime_profiles"]
    assert profiles["tablet_mnn"]["model"] == "qwen3.5-vl-2b-mnn"
    assert profiles["server"]["model"] == "qwen3.5-vl-8b-int4"
    assert data["provider_compatibility"]["mainstream_llm_vlm_adapters_supported"] is True


def test_checkpoint_categories_endpoint(client):
    data = client.get("/api/qc-model/checkpoint-categories").json()
    by_cat = {c["category"]: c for c in data["categories"]}
    assert by_cat["visual_defect"]["ai_can_be_primary_judge"] is True
    assert by_cat["physical_measurement"]["ai_can_be_primary_judge"] is False
    assert by_cat["physical_measurement"]["default_ai_role"] == "record_only"


def test_lifecycle_endpoint(client):
    states = client.get("/api/qc-model/lifecycle").json()["states"]
    assert states[0] == "draft"
    assert "on_trial" in states and "active" in states and "suspended" in states


def test_detection_points_get_proposed_categories(client, seeded):
    data = client.get(f"/api/qc/skus/{seeded['sku_id']}/detection-points").json()
    by_code = {p["point_code"]: p for p in data["detection_points"]}
    # The physical-measurement DP is proposed as physical_measurement.
    assert by_code["chain_link_count"]["proposed_checkpoint_category"] == "physical_measurement"
    # The visual defect is proposed as visual_defect.
    assert by_code["missing_rhinestone"]["proposed_checkpoint_category"] == "visual_defect"
    # Nothing is confirmed yet.
    assert by_code["missing_rhinestone"]["is_confirmed"] is False
    assert by_code["missing_rhinestone"]["ai_can_be_primary_judge"] is False


def test_confirm_category_endpoint(client, seeded):
    resp = client.post(
        f"/api/qc/detection-points/{seeded['visual']}/confirm-category",
        data={"confirmed_category": "visual_defect", "confirmed_by": "sup1", "rationale": "visual"},
    )
    assert resp.status_code == 200
    view = resp.json()
    assert view["is_confirmed"] is True
    assert view["confirmed_checkpoint_category"] == "visual_defect"
    assert view["ai_can_be_primary_judge"] is True


def test_confirm_unsupported_category_rejected(client, seeded):
    resp = client.post(
        f"/api/qc/detection-points/{seeded['physical']}/confirm-category",
        data={"confirmed_category": "made_up", "confirmed_by": "sup1"},
    )
    assert resp.status_code == 400


def test_admin_panel_renders(client, seeded):
    resp = client.get("/admin/qc-model")
    assert resp.status_code == 200
    body = resp.text
    assert "Visual QC Training Engine" in body
    assert "qwen3.5-vl-2b-mnn" in body
    assert "qwen3.5-vl-8b-int4" in body
    assert "Missing rhinestone" in body


def test_admin_panel_linked_from_samples_nav(client):
    resp = client.get("/admin/samples")
    assert resp.status_code == 200
    assert "/admin/qc-model" in resp.text
