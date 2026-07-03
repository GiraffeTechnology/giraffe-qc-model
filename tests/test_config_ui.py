"""End-to-end walkthrough of the Configuration / Training UI (Part B).

create SKU → upload standard photo → submit raw intake → extract →
edit points → confirm/activate revision → SKU shows "trained" on dashboard.
"""
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
import src.db.intake_models  # noqa: F401
import src.db.execution_models  # noqa: F401
import src.db.pad_models  # noqa: F401
from src.api.main import app
from src.api.deps import get_db_dep
from src.config_ui.service import compute_training_status
from src.db.sku_models import QCSkuItem
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
def client(db_session_factory):
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
                username="eng",
                display_name="Engineer",
                role="engineer",
                preferred_language="en",
                password_hash=_make_password_hash("pw"),
                is_active=True,
            )
        )
        s.commit()
    finally:
        s.close()

    with TestClient(app, follow_redirects=True) as c:
        c.post("/admin/login", data={"username": "eng", "password": "pw", "tenant_id": TENANT})
        yield c
    app.dependency_overrides.clear()


def _sku_id(db_session_factory, item_number: str) -> str:
    s = db_session_factory()
    try:
        return (
            s.query(QCSkuItem)
            .filter_by(tenant_id=TENANT, item_number=item_number)
            .first()
            .id
        )
    finally:
        s.close()


def test_engineer_can_reach_dashboard(client):
    resp = client.get("/admin/training")
    assert resp.status_code == 200
    assert "Digital Inspector Training" in resp.text
    # Concept alignment copy is present (training = configuration, not fine-tuning).
    assert "Model weights are fixed" in resp.text


def test_full_training_flow_marks_sku_trained(client, db_session_factory):
    # 1. Create SKU via admin UI.
    client.post("/admin/samples", data={"item_number": "TRAIN-001", "name": "Trainee"})
    sku_id = _sku_id(db_session_factory, "TRAIN-001")

    # 2. Upload a standard photo (hardened path).
    r = client.post(
        f"/admin/samples/{sku_id}/photos",
        files={"photo_file": ("s.png", _PNG, "image/png")},
        data={"is_primary": "true"},
    )
    assert r.status_code == 200

    # 3. Submit raw intake text.
    r = client.post(
        f"/admin/samples/{sku_id}/intakes",
        data={"raw_text": "颜色必须为红色。\n花瓣不得缺失。"},
    )
    assert r.status_code == 200
    intake_id = _latest_intake_id(db_session_factory, sku_id)

    # 4. Extract candidate detection points.
    r = client.post(f"/admin/intakes/{intake_id}/extract")
    assert r.status_code == 200

    # 5. Confirm / activate a revision with an edited detection point.
    r = client.post(
        f"/admin/intakes/{intake_id}/confirm",
        data={
            "point_code": ["COLOR", ""],
            "label": ["Color is red", ""],
            "severity": ["major", "major"],
            "pass_criteria": ["Must be red", ""],
            "description": ["", ""],
            "operator_comment": "looks good",
        },
    )
    assert r.status_code == 200

    # 6. SKU is now trained per the dashboard status computation.
    s = db_session_factory()
    try:
        sku = s.query(QCSkuItem).filter_by(id=sku_id).first()
        status = compute_training_status(s, sku)
        assert status.has_photos is True
        assert status.has_active_revision is True
        assert status.detection_point_count >= 1
        assert status.trained is True
    finally:
        s.close()

    # And the dashboard HTML shows the trained badge.
    dash = client.get("/admin/training")
    assert "TRAIN-001" in dash.text
    assert "Trained" in dash.text


def test_confirm_preserves_extracted_checkpoint_semantics(client, db_session_factory):
    """Codex P1: extract → review/edit → confirm must not drop method_hint,
    expected_value, or the operator-edited pass_criteria (e.g. "pearl count 3")."""
    from src.db.sku_models import QCDetectionPoint

    client.post("/admin/samples", data={"item_number": "COUNT-001", "name": "Pearl Brooch"})
    sku_id = _sku_id(db_session_factory, "COUNT-001")

    client.post(
        f"/admin/samples/{sku_id}/intakes",
        data={"raw_text": "珍珠数量必须为3颗。"},
    )
    intake_id = _latest_intake_id(db_session_factory, sku_id)
    assert client.post(f"/admin/intakes/{intake_id}/extract").status_code == 200

    # Operator reviews and confirms a counting rule with count value + method hint.
    r = client.post(
        f"/admin/intakes/{intake_id}/confirm",
        data={
            "point_code": ["PEARL_COUNT", ""],
            "label": ["Pearl count", ""],
            "severity": ["critical", "major"],
            "expected_value": ["3", ""],
            "method_hint": ["count", ""],
            "pass_criteria": ["Exactly 3 pearls present", ""],
            "description": ["", ""],
            "operator_comment": "counting rule",
        },
    )
    assert r.status_code == 200

    s = db_session_factory()
    try:
        dp = (
            s.query(QCDetectionPoint)
            .filter_by(tenant_id=TENANT, sku_id=sku_id, point_code="PEARL_COUNT", is_active=True)
            .first()
        )
        assert dp is not None, "confirmed detection point should exist"
        # These three fail on the pre-fix router (fields dropped / no column).
        assert dp.expected_value == "3"
        assert dp.method_hint == "count"
        assert dp.pass_criteria == "Exactly 3 pearls present"
    finally:
        s.close()


def test_unconfirmed_intake_does_not_activate(client, db_session_factory):
    client.post("/admin/samples", data={"item_number": "TRAIN-002", "name": "Untrained"})
    sku_id = _sku_id(db_session_factory, "TRAIN-002")
    client.post(f"/admin/samples/{sku_id}/intakes", data={"raw_text": "Some requirement."})

    # No confirmation → no active revision → not trained.
    s = db_session_factory()
    try:
        sku = s.query(QCSkuItem).filter_by(id=sku_id).first()
        status = compute_training_status(s, sku)
        assert status.trained is False
        assert status.has_active_revision is False
    finally:
        s.close()


def _latest_intake_id(db_session_factory, sku_id: str) -> str:
    from src.db.intake_models import QCStandardIntake

    s = db_session_factory()
    try:
        return (
            s.query(QCStandardIntake)
            .filter_by(sku_id=sku_id)
            .order_by(QCStandardIntake.created_at.desc())
            .first()
            .id
        )
    finally:
        s.close()
