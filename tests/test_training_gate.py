"""Tests for the rolling 29/30-window training publish gate
(PRD workflow §9.6/9.7)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models  # noqa: F401
import src.db.training_models  # noqa: F401
from src.db.sku_models import QCSkuItem, QCSkuStandardRevision
from src.db.training_models import QCTrainingJudgment
from src.qc_model.qualification.training_gate import evaluate_training_gate

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
def revision(db_session):
    now = datetime.now(timezone.utc)
    sku = QCSkuItem(
        id=uuid.uuid4().hex, tenant_id=TENANT, item_number="GATE-001",
        name="Training gate test", status="active", created_at=now, updated_at=now,
    )
    db_session.add(sku)
    rev = QCSkuStandardRevision(
        id=uuid.uuid4().hex, sku_id=sku.id, tenant_id=TENANT, revision_no=1,
        status="active", created_at=now, updated_at=now,
    )
    db_session.add(rev)
    db_session.commit()
    return sku, rev


def _add_judgment(
    db_session, sku, rev, *, ground_truth_label, admin_decision, is_false_pass=False,
    reviewed_offset_seconds, status="reviewed", correction_point_code=None,
):
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    j = QCTrainingJudgment(
        id=uuid.uuid4().hex, tenant_id=TENANT, sku_id=sku.id,
        standard_revision_id=rev.id,
        ground_truth_label=ground_truth_label,
        model_overall_result="pass" if ground_truth_label == "qualified" else "fail",
        model_checkpoint_results_json=[{"point_code": "PT1", "result": "pass"}],
        status=status,
        admin_decision=admin_decision,
        admin_id="admin-1" if admin_decision else None,
        reviewed_at=(base + timedelta(seconds=reviewed_offset_seconds)) if status == "reviewed" else None,
        correction_json=({"point_code": correction_point_code, "model_error": "x", "correct_conclusion": "y", "correct_facts": "z"}
                          if correction_point_code else None),
        is_false_pass=is_false_pass,
        created_at=base + timedelta(seconds=reviewed_offset_seconds),
    )
    db_session.add(j)
    db_session.commit()
    return j


def _fill_alternating(db_session, sku, rev, n, *, all_correct=True, false_pass_at=None, offset=0):
    """Insert n reviewed judgments, alternating qualified/unqualified ground
    truth so "covers both labels" is trivially satisfied. ``offset`` shifts
    the reviewed_at/created_at sequence so multiple batches never collide."""
    for i in range(n):
        label = "qualified" if i % 2 == 0 else "unqualified"
        decision = "correct" if all_correct else ("correct" if i != n - 1 else "incorrect")
        _add_judgment(
            db_session, sku, rev,
            ground_truth_label=label, admin_decision=decision,
            is_false_pass=(i == false_pass_at),
            reviewed_offset_seconds=offset + i,
        )


def test_insufficient_samples_never_qualifies(db_session, revision):
    sku, rev = revision
    _fill_alternating(db_session, sku, rev, 10)
    status = evaluate_training_gate(db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id)
    assert status.qualified is False
    assert status.total_reviewed == 10
    assert status.recent_29_correct is None
    assert status.recent_30_correct is None


def test_29_of_29_all_correct_qualifies(db_session, revision):
    sku, rev = revision
    _fill_alternating(db_session, sku, rev, 29, all_correct=True)
    status = evaluate_training_gate(db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id)
    assert status.qualified is True
    assert status.reason == "qualified_29_of_29"
    assert status.recent_29_correct == 29


def test_29_of_30_with_one_wrong_qualifies(db_session, revision):
    sku, rev = revision
    # 30 samples, only the last (index 29) is incorrect -> the last-29
    # window (indices 1..29) contains that one incorrect record, so 29/29
    # fails, but the last-30 window has 29 correct out of 30.
    _fill_alternating(db_session, sku, rev, 30, all_correct=False)
    status = evaluate_training_gate(db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id)
    assert status.qualified is True
    assert status.reason == "qualified_29_of_30"
    assert status.recent_30_correct == 29
    assert status.recent_29_correct == 28  # last 29 records include the one wrong decision


def test_two_wrong_in_last_30_does_not_qualify(db_session, revision):
    sku, rev = revision
    for i in range(30):
        label = "qualified" if i % 2 == 0 else "unqualified"
        decision = "incorrect" if i in (28, 29) else "correct"
        _add_judgment(db_session, sku, rev, ground_truth_label=label, admin_decision=decision, reviewed_offset_seconds=i)
    status = evaluate_training_gate(db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id)
    assert status.qualified is False
    assert status.recent_30_correct == 28


def test_false_pass_in_window_blocks_qualification_even_if_count_would_pass(db_session, revision):
    sku, rev = revision
    _fill_alternating(db_session, sku, rev, 29, all_correct=True, false_pass_at=5)
    status = evaluate_training_gate(db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id)
    assert status.qualified is False
    assert "false_pass" in status.reason


def test_window_missing_a_ground_truth_label_blocks_qualification(db_session, revision):
    sku, rev = revision
    # All 29 samples share the same ground-truth label -> the window never
    # exercised the other label, so it cannot qualify no matter how correct.
    for i in range(29):
        _add_judgment(
            db_session, sku, rev, ground_truth_label="qualified",
            admin_decision="correct", reviewed_offset_seconds=i,
        )
    status = evaluate_training_gate(db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id)
    assert status.qualified is False
    assert status.reason == "window_missing_a_ground_truth_label"


def test_only_reviewed_judgments_count_toward_the_window(db_session, revision):
    sku, rev = revision
    _fill_alternating(db_session, sku, rev, 28, all_correct=True)
    # An unreviewed record must not push the count to 29.
    _add_judgment(
        db_session, sku, rev, ground_truth_label="unqualified", admin_decision=None,
        status="awaiting_admin_review", reviewed_offset_seconds=100,
    )
    status = evaluate_training_gate(db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id)
    assert status.total_reviewed == 28
    assert status.qualified is False
    assert status.recent_29_correct is None


def test_older_failures_do_not_permanently_block_a_now_qualifying_window(db_session, revision):
    """PRD §9.7: 'early failures still permanently remain in the audit
    history' but must not permanently block qualification -- only the most
    recent window matters."""
    sku, rev = revision
    # First 10 are all wrong (early training pains).
    for i in range(10):
        label = "qualified" if i % 2 == 0 else "unqualified"
        _add_judgment(db_session, sku, rev, ground_truth_label=label, admin_decision="incorrect", reviewed_offset_seconds=i)
    # Next 29 are all correct (offset past the first batch) -> should
    # qualify on the strict window regardless of the earlier failures.
    _fill_alternating(db_session, sku, rev, 29, all_correct=True, offset=10)
    status = evaluate_training_gate(db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id)
    assert status.qualified is True
    assert status.total_reviewed == 39


def test_per_checkpoint_accuracy_reflects_named_correction(db_session, revision):
    sku, rev = revision
    _add_judgment(db_session, sku, rev, ground_truth_label="qualified", admin_decision="correct", reviewed_offset_seconds=0)
    _add_judgment(
        db_session, sku, rev, ground_truth_label="unqualified", admin_decision="incorrect",
        reviewed_offset_seconds=1, correction_point_code="PT1",
    )
    status = evaluate_training_gate(db_session, tenant_id=TENANT, sku_id=sku.id, standard_revision_id=rev.id)
    assert status.per_checkpoint_accuracy["PT1"]["total"] == 2
    assert status.per_checkpoint_accuracy["PT1"]["correct"] == 1
