"""Tests for the QC standard lifecycle and inspection execution pipeline.

Covers:
1.  New SKU has no active standard revision
2.  create_standard_revision produces a 'draft' revision
3.  confirm_standard_revision activates the revision and records confirmed_by/at
4.  Confirming a second revision archives the first, activates the second
5.  create_inspection_job snapshots the active revision
6.  get_active_detection_points_for_job returns only the job's revision points
7.  All checkpoints pass, no serious findings → overall_result = 'pass'
8.  Missing checkpoint result → overall_result = 'review_required' (no-guess policy)
9.  low_confidence or not_visible checkpoint result → overall_result = 'review_required'
10. All checkpoints pass but major incidental finding → 'review_required'
11. Explicit checkpoint fail → overall_result = 'fail'
12. Duplicate checkpoint result → rejected
13. Detection point not from job's revision/SKU/tenant → rejected
14. Inactive detection point → rejected
15. finalize_job is idempotent
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


def _make_detection_point(
    db,
    sku_id: str,
    revision_id: str,
    code: str,
    severity: str = "major",
    tenant_id: str = "t1",
    is_active: bool = True,
) -> QCDetectionPoint:
    import uuid
    dp = QCDetectionPoint(
        id=uuid.uuid4().hex,
        tenant_id=tenant_id,
        sku_id=sku_id,
        standard_revision_id=revision_id,
        point_code=code,
        label=code.replace("_", " ").title(),
        severity=severity,
        sort_order=1,
        is_active=is_active,
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


def test_finalize_job_with_zero_detection_points_never_passes(db):
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")

    job = create_inspection_job(db, sku.id, "t1")

    report = finalize_job(db, job.id)
    assert report.overall_result == "review_required"
    assert report.checkpoint_results_count == 0
    assert "No active detection points" in (report.summary_text or "")


# ── Test 8 ────────────────────────────────────────────────────────────────────

def test_missing_checkpoint_result_yields_review_required(db):
    """No-guess policy: missing checkpoint → cannot verify → review_required, not fail."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp1 = _make_detection_point(db, sku.id, rev.id, "POINT_A")
    _make_detection_point(db, sku.id, rev.id, "POINT_B")  # no result submitted

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp1.id, "pass")
    # POINT_B intentionally left without a result

    report = finalize_job(db, job.id)
    assert report.overall_result == "review_required"


# ── Test 9 ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("uncertain_result", ["low_confidence", "not_visible"])
def test_non_definitive_checkpoint_yields_review_required(db, uncertain_result):
    """Uncertain results cannot verify the checkpoint → review_required, not fail."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp = _make_detection_point(db, sku.id, rev.id, "POINT_A")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp.id, uncertain_result)

    report = finalize_job(db, job.id)
    assert report.overall_result == "review_required"


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


# ── Test 11 ───────────────────────────────────────────────────────────────────

def test_explicit_checkpoint_fail_produces_fail(db):
    """Visual evidence of failure → verdict = fail (not review_required)."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp1 = _make_detection_point(db, sku.id, rev.id, "POINT_A")
    dp2 = _make_detection_point(db, sku.id, rev.id, "POINT_B")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp1.id, "pass")
    submit_checkpoint_result(db, job.id, dp2.id, "fail")

    report = finalize_job(db, job.id)
    assert report.overall_result == "fail"


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


# ── Product acceptance tests (exact names required by PRD) ───────────────────


def test_same_sku_reuses_active_standard_without_reconfirmation(db):
    """Multiple jobs on the same SKU all use the active revision without re-confirming."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id="t1")

    job1 = create_inspection_job(db, sku.id, "t1")
    job2 = create_inspection_job(db, sku.id, "t1")
    job3 = create_inspection_job(db, sku.id, "t1")

    # All three jobs snapshot the same revision — no extra confirmation needed
    assert job1.active_standard_revision_id == rev.id
    assert job2.active_standard_revision_id == rev.id
    assert job3.active_standard_revision_id == rev.id


def test_standard_update_creates_new_revision_only_on_operator_request(db):
    """The standard is not updated automatically; only an explicit create+confirm call changes it."""
    sku = _make_sku(db)
    rev1 = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev1.id, "alice", "t1")

    # Without any operator action the active revision stays the same
    assert get_active_standard_revision(db, sku.id, "t1").id == rev1.id

    # An operator explicitly requests an update
    rev2 = create_standard_revision(db, sku.id, "t1", reason="operator requested: add new checkpoint")
    assert rev2.status == "draft"  # not yet active — must be confirmed
    assert get_active_standard_revision(db, sku.id, "t1").id == rev1.id  # still old

    # Operator confirms the new revision
    confirm_standard_revision(db, rev2.id, "bob", "t1")
    assert get_active_standard_revision(db, sku.id, "t1").id == rev2.id


def test_old_inspection_job_keeps_old_standard_revision(db):
    """Updating the standard does not retroactively change existing jobs' snapshots."""
    sku = _make_sku(db)
    rev1 = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev1.id, "alice", "t1")

    old_job = create_inspection_job(db, sku.id, "t1")
    assert old_job.active_standard_revision_id == rev1.id

    # Operator updates the standard
    rev2 = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev2.id, "alice", "t1")

    # New jobs use the new revision
    new_job = create_inspection_job(db, sku.id, "t1")
    assert new_job.active_standard_revision_id == rev2.id

    # Old job is unchanged
    db.refresh(old_job)
    assert old_job.active_standard_revision_id == rev1.id


def test_missing_checkpoint_result_blocks_pass(db):
    """A checkpoint with no submitted result auto-becomes 'missing' → review_required, not fail."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp1 = _make_detection_point(db, sku.id, rev.id, "ALPHA")
    _make_detection_point(db, sku.id, rev.id, "BETA")  # no result submitted

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp1.id, "pass")

    report = finalize_job(db, job.id)
    assert report.overall_result == "review_required"


def test_not_visible_checkpoint_blocks_pass(db):
    """A checkpoint result of 'not_visible' → cannot verify → review_required."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp = _make_detection_point(db, sku.id, rev.id, "ALPHA")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp.id, "not_visible")

    report = finalize_job(db, job.id)
    assert report.overall_result == "review_required"


def test_low_confidence_checkpoint_blocks_pass(db):
    """A checkpoint result of 'low_confidence' → cannot verify → review_required."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp = _make_detection_point(db, sku.id, rev.id, "ALPHA")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp.id, "low_confidence", confidence=0.4)

    report = finalize_job(db, job.id)
    assert report.overall_result == "review_required"


def test_major_incidental_finding_creates_review_required(db):
    """When all checkpoints pass but a major incidental finding is present → review_required."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp = _make_detection_point(db, sku.id, rev.id, "ALPHA")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp.id, "pass")
    submit_incidental_finding(db, job.id, "Surface scratch on back panel", severity="major")

    report = finalize_job(db, job.id)
    assert report.overall_result == "review_required"


def test_flower_brooch_seed_has_required_four_checkpoints(db):
    """FLOWER-BROOCH-001 seed contains exactly the four mandated checkpoints."""
    sku = seed_flower_brooch(db, tenant_id="t1")
    active = get_active_standard_revision(db, sku.id, "t1")
    assert active is not None

    points = (
        db.query(QCDetectionPoint)
        .filter_by(standard_revision_id=active.id, is_active=True)
        .all()
    )
    code_map = {p.point_code: p for p in points}
    assert set(code_map.keys()) == {"STAMEN_CENTERING", "PEARL_COUNT", "RHINESTONE_COUNT", "PETAL_INTEGRITY"}
    assert code_map["STAMEN_CENTERING"].severity == "major"
    assert code_map["PEARL_COUNT"].severity == "critical"
    assert code_map["PEARL_COUNT"].expected_value == "3"
    assert code_map["RHINESTONE_COUNT"].severity == "critical"
    assert code_map["RHINESTONE_COUNT"].expected_value == "8"
    assert code_map["PETAL_INTEGRITY"].severity == "critical"


def test_no_guess_policy_cannot_pass_without_full_checkpoint_coverage(db):
    """Submitting results for only a subset of checkpoints → review_required (missing checkpoint)."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp1 = _make_detection_point(db, sku.id, rev.id, "ALPHA")
    dp2 = _make_detection_point(db, sku.id, rev.id, "BETA")
    dp3 = _make_detection_point(db, sku.id, rev.id, "GAMMA")

    job = create_inspection_job(db, sku.id, "t1")
    # Only submit results for 2 of 3 checkpoints
    submit_checkpoint_result(db, job.id, dp1.id, "pass")
    submit_checkpoint_result(db, job.id, dp2.id, "pass")
    # dp3 intentionally omitted

    report = finalize_job(db, job.id)
    assert report.overall_result == "review_required"
    assert report.checkpoint_results_count == 3


# ── New acceptance tests ──────────────────────────────────────────────────────


def test_duplicate_checkpoint_result_rejected(db):
    """Submitting a second result for the same (job, detection_point) pair raises ValueError."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp = _make_detection_point(db, sku.id, rev.id, "ALPHA")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp.id, "pass")

    with pytest.raises(ValueError, match="already exists"):
        submit_checkpoint_result(db, job.id, dp.id, "fail")


def test_checkpoint_result_rejects_point_from_other_sku(db):
    """submit_checkpoint_result rejects a detection point that belongs to a different SKU."""
    sku_a = _make_sku(db, item_number="SKU-A")
    sku_b = _make_sku(db, item_number="SKU-B")

    rev_a = create_standard_revision(db, sku_a.id, "t1")
    confirm_standard_revision(db, rev_a.id, "alice", "t1")

    rev_b = create_standard_revision(db, sku_b.id, "t1")
    confirm_standard_revision(db, rev_b.id, "alice", "t1")

    dp_b = _make_detection_point(db, sku_b.id, rev_b.id, "POINT_B_SKU")

    job_a = create_inspection_job(db, sku_a.id, "t1")

    with pytest.raises(ValueError, match="SKU"):
        submit_checkpoint_result(db, job_a.id, dp_b.id, "pass")


def test_checkpoint_result_rejects_point_from_other_revision(db):
    """submit_checkpoint_result rejects a detection point from a different standard revision."""
    sku = _make_sku(db)
    rev1 = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev1.id, "alice", "t1")

    rev2 = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev2.id, "alice", "t1")
    dp_rev2 = _make_detection_point(db, sku.id, rev2.id, "POINT_REV2")

    # Job was created when rev1 was active — it snapshots rev1
    job = create_inspection_job(db, sku.id, "t1")
    # Sanity: job should have snapped rev2 since that's now active
    # So create job when rev1 was active instead
    # Let's redo: create job before confirming rev2
    sku2 = _make_sku(db, item_number="SKU-REV-TEST")
    rev_old = create_standard_revision(db, sku2.id, "t1")
    confirm_standard_revision(db, rev_old.id, "alice", "t1")
    job2 = create_inspection_job(db, sku2.id, "t1")
    assert job2.active_standard_revision_id == rev_old.id

    rev_new = create_standard_revision(db, sku2.id, "t1")
    confirm_standard_revision(db, rev_new.id, "alice", "t1")
    dp_new = _make_detection_point(db, sku2.id, rev_new.id, "POINT_NEW_REV")

    with pytest.raises(ValueError, match="revision"):
        submit_checkpoint_result(db, job2.id, dp_new.id, "pass")


def test_checkpoint_result_rejects_point_from_other_tenant(db):
    """submit_checkpoint_result rejects a detection point that belongs to a different tenant."""
    sku_t1 = _make_sku(db, item_number="SKU-T1", tenant_id="t1")
    sku_t2 = _make_sku(db, item_number="SKU-T2", tenant_id="t2")

    rev_t1 = create_standard_revision(db, sku_t1.id, "t1")
    confirm_standard_revision(db, rev_t1.id, "alice", "t1")

    rev_t2 = create_standard_revision(db, sku_t2.id, "t2")
    confirm_standard_revision(db, rev_t2.id, "alice", "t2")
    dp_t2 = _make_detection_point(db, sku_t2.id, rev_t2.id, "POINT_T2", tenant_id="t2")

    job_t1 = create_inspection_job(db, sku_t1.id, "t1")

    with pytest.raises(ValueError, match="tenant"):
        submit_checkpoint_result(db, job_t1.id, dp_t2.id, "pass")


def test_checkpoint_result_rejects_inactive_point(db):
    """submit_checkpoint_result rejects a detection point that is not active."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp_inactive = _make_detection_point(db, sku.id, rev.id, "INACTIVE_POINT", is_active=False)

    job = create_inspection_job(db, sku.id, "t1")

    with pytest.raises(ValueError, match="not active"):
        submit_checkpoint_result(db, job.id, dp_inactive.id, "pass")


def test_finalize_job_is_idempotent(db):
    """Calling finalize_job twice returns the same report without raising or creating duplicates."""
    sku = _make_sku(db)
    rev = create_standard_revision(db, sku.id, "t1")
    confirm_standard_revision(db, rev.id, "alice", "t1")
    dp = _make_detection_point(db, sku.id, rev.id, "ALPHA")

    job = create_inspection_job(db, sku.id, "t1")
    submit_checkpoint_result(db, job.id, dp.id, "pass")

    report1 = finalize_job(db, job.id)
    report2 = finalize_job(db, job.id)

    assert report1.id == report2.id
    assert report2.overall_result == "pass"
