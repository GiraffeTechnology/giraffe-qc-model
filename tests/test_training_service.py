"""Tests for training-judgment recording and admin review
(PRD workflow §9.5-9.8)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models  # noqa: F401
import src.db.training_models  # noqa: F401
from src.db.sku_models import QCDetectionPoint, QCSkuItem, QCSkuStandardRevision
from src.db.training_models import QCTrainingJudgment
from src.qc_model.qualification import training
from src.qc_model.studio import ai_gateway

TENANT = "default"


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def revision_with_point(db_session):
    now = datetime.now(timezone.utc)
    sku = QCSkuItem(
        id=uuid.uuid4().hex, tenant_id=TENANT, item_number="TRAIN-001",
        name="Training service test", status="active", created_at=now, updated_at=now,
    )
    db_session.add(sku)
    rev = QCSkuStandardRevision(
        id=uuid.uuid4().hex, sku_id=sku.id, tenant_id=TENANT, revision_no=1,
        status="active", created_at=now, updated_at=now,
    )
    db_session.add(rev)
    point = QCDetectionPoint(
        id=uuid.uuid4().hex, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id,
        point_code="SURFACE_DAMAGE", label="Surface damage", method_hint="defect_detection",
        severity="major", sort_order=0, is_active=True, created_at=now, updated_at=now,
    )
    db_session.add(point)
    db_session.commit()
    return sku, rev


def test_record_training_judgment_requires_a_valid_ground_truth_label(db_session, revision_with_point, tmp_path):
    sku, rev = revision_with_point
    with pytest.raises(training.TrainingError, match="ground_truth_label"):
        training.record_training_judgment(
            db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id,
            image_path=tmp_path / "x.png", mime_type="image/png", language="en",
            ground_truth_label="maybe", evidence_root=tmp_path,
        )


def test_record_training_judgment_requires_active_detection_points(db_session, tmp_path):
    now = datetime.now(timezone.utc)
    sku = QCSkuItem(
        id=uuid.uuid4().hex, tenant_id=TENANT, item_number="TRAIN-EMPTY",
        name="No points", status="active", created_at=now, updated_at=now,
    )
    db_session.add(sku)
    rev = QCSkuStandardRevision(
        id=uuid.uuid4().hex, sku_id=sku.id, tenant_id=TENANT, revision_no=1,
        status="active", created_at=now, updated_at=now,
    )
    db_session.add(rev)
    db_session.commit()
    with pytest.raises(training.TrainingError, match="no active detection points"):
        training.record_training_judgment(
            db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id,
            image_path=tmp_path / "x.png", mime_type="image/png", language="en",
            ground_truth_label="qualified", evidence_root=tmp_path,
        )


def test_record_training_judgment_records_pass_for_qualified_sample(db_session, revision_with_point, tmp_path, monkeypatch):
    sku, rev = revision_with_point
    image = tmp_path / "sample.png"
    image.write_bytes(b"fake-image")

    def fake_inspect_image(**kwargs):
        return {
            "summary": "clean",
            "checkpoint_results": [{
                "point_code": "SURFACE_DAMAGE", "result": "pass", "confidence": 0.9,
                "observed_value": "no damage", "notes": "clean surface",
            }],
            "assistant": {"role": "vision", "provider": "openai_compatible", "model": "local-4b", "elapsed_ms": 120, "mode": "live"},
        }

    monkeypatch.setattr(ai_gateway, "inspect_image", fake_inspect_image)
    judgment = training.record_training_judgment(
        db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id,
        image_path=image, mime_type="image/png", language="en",
        ground_truth_label="qualified", evidence_root=tmp_path,
    )
    assert judgment.status == "awaiting_admin_review"
    assert judgment.model_overall_result == "pass"
    assert judgment.is_false_pass is False
    assert judgment.admin_decision is None


def test_record_training_judgment_flags_false_pass(db_session, revision_with_point, tmp_path, monkeypatch):
    sku, rev = revision_with_point
    image = tmp_path / "sample.png"
    image.write_bytes(b"fake-image")

    def fake_inspect_image(**kwargs):
        return {
            "summary": "looks fine to the model, but the sample is actually defective",
            "checkpoint_results": [{
                "point_code": "SURFACE_DAMAGE", "result": "pass", "confidence": 0.9,
                "observed_value": "no damage", "notes": "missed defect",
            }],
            "assistant": {"role": "vision", "provider": "openai_compatible", "model": "local-4b", "elapsed_ms": 120, "mode": "live"},
        }

    monkeypatch.setattr(ai_gateway, "inspect_image", fake_inspect_image)
    judgment = training.record_training_judgment(
        db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id,
        image_path=image, mime_type="image/png", language="en",
        ground_truth_label="unqualified", evidence_root=tmp_path,
    )
    assert judgment.model_overall_result == "pass"
    assert judgment.is_false_pass is True


def test_record_training_judgment_treats_low_confidence_as_not_a_clean_pass(db_session, revision_with_point, tmp_path, monkeypatch):
    sku, rev = revision_with_point
    image = tmp_path / "sample.png"
    image.write_bytes(b"fake-image")

    def fake_inspect_image(**kwargs):
        return {
            "summary": "ambiguous",
            "checkpoint_results": [{
                "point_code": "SURFACE_DAMAGE", "result": "low_confidence", "confidence": 0.4,
                "observed_value": None, "notes": "glare",
            }],
            "assistant": {"role": "vision", "provider": "openai_compatible", "model": "local-4b", "elapsed_ms": 120, "mode": "live"},
        }

    monkeypatch.setattr(ai_gateway, "inspect_image", fake_inspect_image)
    judgment = training.record_training_judgment(
        db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id,
        image_path=image, mime_type="image/png", language="en",
        ground_truth_label="qualified", evidence_root=tmp_path,
    )
    assert judgment.model_overall_result == "fail"
    assert judgment.is_false_pass is False


def _make_judgment(db_session, sku, rev):
    j = QCTrainingJudgment(
        id=uuid.uuid4().hex, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id,
        ground_truth_label="qualified", model_overall_result="pass",
        model_checkpoint_results_json=[{"point_code": "SURFACE_DAMAGE", "result": "pass"}],
        status="awaiting_admin_review", is_false_pass=False,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(j)
    db_session.commit()
    return j


def test_submit_decision_correct_marks_reviewed(db_session, revision_with_point):
    sku, rev = revision_with_point
    judgment = _make_judgment(db_session, sku, rev)
    reviewed = training.submit_training_decision(
        db_session, judgment_id=judgment.id, tenant_id=TENANT, admin_id="admin-1", decision="correct",
    )
    assert reviewed.status == "reviewed"
    assert reviewed.admin_decision == "correct"
    assert reviewed.admin_id == "admin-1"
    assert reviewed.reviewed_at is not None


def test_submit_decision_incorrect_requires_full_correction(db_session, revision_with_point):
    sku, rev = revision_with_point
    judgment = _make_judgment(db_session, sku, rev)
    with pytest.raises(training.TrainingError, match="correction is required"):
        training.submit_training_decision(
            db_session, judgment_id=judgment.id, tenant_id=TENANT, admin_id="admin-1", decision="incorrect",
        )
    with pytest.raises(training.TrainingError, match="missing required fields"):
        training.submit_training_decision(
            db_session, judgment_id=judgment.id, tenant_id=TENANT, admin_id="admin-1",
            decision="incorrect", correction={"point_code": "SURFACE_DAMAGE"},
        )


def test_submit_decision_incorrect_with_full_correction_persists_it(db_session, revision_with_point):
    sku, rev = revision_with_point
    judgment = _make_judgment(db_session, sku, rev)
    reviewed = training.submit_training_decision(
        db_session, judgment_id=judgment.id, tenant_id=TENANT, admin_id="admin-1",
        decision="incorrect",
        correction={
            "point_code": "SURFACE_DAMAGE", "model_error": "missed a scratch",
            "correct_conclusion": "fail", "correct_facts": "visible scratch on the left edge",
        },
    )
    assert reviewed.correction_json["point_code"] == "SURFACE_DAMAGE"
    assert reviewed.correction_json["model_error"] == "missed a scratch"


def test_submit_decision_is_append_only(db_session, revision_with_point):
    sku, rev = revision_with_point
    judgment = _make_judgment(db_session, sku, rev)
    training.submit_training_decision(
        db_session, judgment_id=judgment.id, tenant_id=TENANT, admin_id="admin-1", decision="correct",
    )
    with pytest.raises(training.TrainingError, match="already reviewed"):
        training.submit_training_decision(
            db_session, judgment_id=judgment.id, tenant_id=TENANT, admin_id="admin-2", decision="incorrect",
            correction={"point_code": "X", "model_error": "y", "correct_conclusion": "z", "correct_facts": "w"},
        )


def test_submit_decision_rejects_unknown_judgment(db_session):
    with pytest.raises(training.TrainingError, match="not found"):
        training.submit_training_decision(
            db_session, judgment_id="does-not-exist", tenant_id=TENANT, admin_id="admin-1", decision="correct",
        )


def test_list_pending_judgments_excludes_reviewed(db_session, revision_with_point):
    sku, rev = revision_with_point
    pending = _make_judgment(db_session, sku, rev)
    reviewed = _make_judgment(db_session, sku, rev)
    training.submit_training_decision(
        db_session, judgment_id=reviewed.id, tenant_id=TENANT, admin_id="admin-1", decision="correct",
    )
    result = training.list_pending_judgments(db_session, tenant_id=TENANT, sku_id=sku.id)
    assert [j.id for j in result] == [pending.id]
