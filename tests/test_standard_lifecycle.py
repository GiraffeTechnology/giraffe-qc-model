"""Tests for the QC standard lifecycle and inspection execution pipeline.

Covers:
1.  New SKU has no active standard revision
2.  create_standard_revision produces a 'draft' revision
3.  confirm_standard_revision activates the revision and records confirmed_by/at
4.  Confirming a second revision archives the first, activates the second
5.  create_inspection_job snapshots the active revision
6.  get_active_detection_points_for_job returns only the job's revision points
7.  All checkpoints pass, no serious findings → overall_result = 'pass'
8.  Missing checkpoint result → overall_result = 'fail' (no-guess policy)
9.  low_confidence or not_visible checkpoint result → overall_result = 'fail'
10. All checkpoints pass but major incidental finding → 'review_required'
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_models       # noqa: F401 — register tables
import src.db.sku_models      # noqa: F401 — register tables
import src.db.execution_models  # noqa: F401 — register tables

from src.db.sku_models import QCSkuItem, QCSkuStandardRevision, QCDetectionPoint
from src.db.seed_data import seed_flower_brooch
from src.inspection.service import (
    get_active_standard_revision,
    create_standard_revision,
    confirm_standard_revision,
    create_inspection_job,
    get_active_detection_points_for_job,
    submit_checkpoint_result,
    submit_incidental_finding,
    finalize_job,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _make_sku(db, item_number: str = "TEST-SKU-001", tenant_id: str = "t1") -> QCSkuItem:
    import uuid
    sku = QCSkuItem(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        item_number=item_number,
        name="Test SKU",
        status="active",
    )
    db.add(sku)
    db.commit()
    db.refresh(sku)
    return sku


def _make_detection_point(db, sku_id: str, revision_id: str, code: str, severity: str = "major") -> QCDetectionPoint:
    import uuid
    dp = QCDetectionPoint(
        id=uuid.uuid4().hex,
        tenant_id="t1",
        sku_id=sku_id,
        standard_revision_id=revision_id,
        point_code=code,
        label=code.replace("_", " ").title(),
        severity=severity,
        sort_order=1,
        is_active=True,
    )
    db.add(dp)
    db.commit()
    db.refresh(dp)
    return dp


# ── Test 1 ────────────────────────────────────────────────────────────────────

def test_new_sku_has_no_active_revision(db):
    sku = _make_sku(db)
    result = get_active_standard_revision(db, sku.id, "t1")
    assert result is None


# ── Test 2 ────────────────────────────────────────────────────────────────────

def test_create_standard_revision_is_draft(db):
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1", created_from="admin_ui")
    assert rev.status == "draft"
    assert rev.revision_no == 1
    assert rev.sku_id == sku.id
    # Still no active revision
    assert get_active_standard_revision(db, sku.id, "t1") is None


# ── Test 3 ────────────────────────────────────────────────────────────────────

def test_confirm_revision_activates_and_records_confirmed_by(db):
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirmed = confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id="t1")

    assert confirmed.status == "active"
    assert confirmed.confirmed_by == "alice"
    assert confirmed.confirmed_at is not None

    active = get_active_standard_revision(db, sku.id, "t1")
    assert active is not None
    assert active.id == rev.id


# ── Test 4 ────────────────────────────────────────────────────────────────────

def test_confirming_second_revision_archives_first(db):
    sku = _make_sku(db)
    rev1 = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev1.id, confirmed_by="alice", tenant_id="t1")

    rev2 = create_standard_revision(db, sku.id, "t1", reason="updated pearl count")
    confirm_standard_revision(db, rev2.id, confirmed_by="bob", tenant_id="t1")

    db.refresh(rev1)
    db.refresh(rev2)

    assert rev1.status == "archived"
    assert rev1.superseded_by_revision == rev2.revision_no
    assert rev2.status == "active"
    assert rev2.revision_no == 2

    active = get_active_standard_revision(db, sku.id, "t1")
    assert active.id == rev2.id


# ── Test 5 ────────────────────────────────────────────────────────────────────

def test_create_inspection_job_snapshots_active_revision(db):
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id="t1")

    job = create_inspection_job(db, sku.id, "t1", job_ref="JOB-001")
    assert job.active_standard_revision_id == rev.id
    assert job.status == "pending"

    # Confirming a new revision does not change the snapshot on the existing job
    rev2 = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev2.id, confirmed_by="alice", tenant_id="t1")
    db.refresh(job)
    assert job.active_standard_revision_id == rev.id


# ── Test 6 ────────────────────────────────────────────────────────────────────

def test_get_active_detection_points_for_job_scoped_to_revision(db):
    sku = _make_sku(db)
    rev1 = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev1.id, "alice", "t1")
    _make_detection_point(db, sku.id, rev1.id, "POINT_A")
    _make_detection_point(db, sku.id, rev1.id, "POINT_B")

    job = create_inspection_job(db, sku.id, "t1")

    # Add a second revision with a different point — should NOT appear for job
    rev2 = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev2.id, "bob", "t1")
    _make_detection_point(db, sku.id, rev2.id, "POINT_C")

    points = get_active_detection_points_for_job(db, job.id)
    codes = {p.point_code for p in points}
    assert codes == {"POINT_A", "POINT_B"}
    assert "POINT_C" not in codes


# ── Test 7 ────────────────────────────────────────────────────────────────────

def test_all_checkpoints_pass_no_findings_yields_pass(db):
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp1 = _make_detection_point(db, sku.id, rev.id, "POINT_A")
    dp2 = _make_detection_point(db, sku.id, rev.id, "POINT_B")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp1.id, "pass")
    submit_checkpoint_result(db, job.id, dp2.id, "pass")

    report = finalize_job(db, job.id)
    assert report.overall_result == "pass"
    assert report.checkpoint_results_count == 2
    assert report.findings_count == 0


# ── Test 8 ────────────────────────────────────────────────────────────────────

def test_missing_checkpoint_result_yields_fail(db):
    """No-guess policy: if a checkpoint has no submitted result → auto-missing → fail."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp1 = _make_detection_point(db, sku.id, rev.id, "POINT_A")
    _make_detection_point(db, sku.id, rev.id, "POINT_B")  # no result submitted

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp1.id, "pass")
    # POINT_B intentionally left without a result

    report = finalize_job(db, job.id)
    assert report.overall_result == "fail"


# ── Test 9 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_result", ["low_confidence", "not_visible"])
def test_non_definitive_checkpoint_yields_fail(db, bad_result):
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp = _make_detection_point(db, sku.id, rev.id, "POINT_A")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp.id, bad_result)

    report = finalize_job(db, job.id)
    assert report.overall_result == "fail"


# ── Test 10 ───────────────────────────────────────────────────────────────────

def test_all_pass_but_major_finding_yields_review_required(db):
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp = _make_detection_point(db, sku.id, rev.id, "POINT_A")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp.id, "pass")
    submit_incidental_finding(db, job.id, "Unexpected discoloration on back surface", severity="major")

    report = finalize_job(db, job.id)
    assert report.overall_result == "review_required"
    assert report.findings_count == 1


# ── Bonus: flower brooch seed ─────────────────────────────────────────────────

def test_flower_brooch_seed_creates_active_revision_with_four_checkpoints(db):
    sku = seed_flower_brooch(db, tenant_id="t1")
    assert sku.item_number == "FLOWER-BROOCH-001"

    active = get_active_standard_revision(db, sku.id, "t1")
    assert active is not None
    assert active.status == "active"

    points = (
        db.query(QCDetectionPoint)
        .filter_by(standard_revision_id=active.id, is_active=True)
        .all()
    )
    codes = {p.point_code for p in points}
    assert codes == {"STAMEN_CENTERING", "PEARL_COUNT", "RHINESTONE_COUNT", "PETAL_INTEGRITY"}

    severities = {p.point_code: p.severity for p in points}
    assert severities["STAMEN_CENTERING"] == "major"
    assert severities["PEARL_COUNT"] == "critical"
    assert severities["RHINESTONE_COUNT"] == "critical"
    assert severities["PETAL_INTEGRITY"] == "critical"

    # Expected values
    expected = {p.point_code: p.expected_value for p in points}
    assert expected["PEARL_COUNT"] == "3"
    assert expected["RHINESTONE_COUNT"] == "8"


def test_create_inspection_job_fails_without_active_revision(db):
    sku = _make_sku(db)
    with pytest.raises(ValueError, match="No active standard revision"):
        create_inspection_job(db, sku.id, "t1")
