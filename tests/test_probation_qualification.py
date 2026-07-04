"""Tests for the Standard Probation / qualification workflow.

PRD "QC Standard Authoring Extension" §3 + acceptance criteria §5:
- New standard enters Probation, mandatory human confirmation per job.
- Agreement rate is not evaluated before 30 real jobs (even at 100%).
- ≥90% at/after the minimum sample size qualifies → Active Inspection.
- Disagreement reports surface per detection point (AI vs. human).
- Admin can pause probation at any time.
- Editing expected_value / pass_criteria resets; description / regions do not.
- Probation is keyed on standard_revision_id, not the SKU.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_probation_models  # noqa: F401 — register tables

from contracts.state_model import (
    StandardState,
    STATE_DISPLAY,
    can_transition,
)
from src.qc_model.qualification.probation import (
    PROBATION_ACTIVE,
    PROBATION_PAUSED,
    PROBATION_QUALIFIED,
    InvalidProbationJob,
    InvalidProbationState,
    ProbationNotActive,
    disagreement_report,
    edit_resets_probation,
    evaluate_gate,
    get_probation_for_revision,
    pause_probation,
    record_probation_job,
    resume_probation,
    start_probation,
)


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


def _record(db, probation, n, agree, ai="pass", human="pass", start=0):
    """Record ``n`` jobs; ``agree`` controls whether AI == human."""
    for i in range(n):
        record_probation_job(
            db, probation.id,
            ai_verdict=ai,
            human_final_verdict=(ai if agree else ("fail" if ai == "pass" else "pass")),
            tenant_id=probation.tenant_id,
            job_ref=f"JOB-{start + i}",
        )


# ── Lifecycle state ───────────────────────────────────────────────────────────


def test_probation_state_inserted_between_installed_and_active():
    assert StandardState.PROBATION.value == "probation"
    assert STATE_DISPLAY[StandardState.PROBATION] == "Probation"
    # Installed goes to Probation (not directly to Active).
    assert can_transition(StandardState.INSTALLED_ON_PAD, StandardState.PROBATION)
    assert not can_transition(StandardState.INSTALLED_ON_PAD, StandardState.ACTIVE_INSPECTION)
    # Probation graduates to solo Active Inspection.
    assert can_transition(StandardState.PROBATION, StandardState.ACTIVE_INSPECTION)
    assert can_transition(StandardState.PROBATION, StandardState.NEEDS_REQUALIFICATION)


# ── Minimum sample size (§3.2) ────────────────────────────────────────────────


def test_below_min_sample_never_qualifies_even_at_100pct(db):
    p = start_probation(db, "REV-1", tenant_id="t1", sku_id="SKU-1")
    _record(db, p, 29, agree=True)  # 29 perfect jobs

    gate = evaluate_gate(p)
    assert gate.jobs_recorded == 29
    assert gate.agreement_rate == 1.0
    assert gate.min_sample_met is False
    assert gate.qualified is False
    assert p.status == PROBATION_ACTIVE


def test_qualifies_at_30_jobs_when_agreement_ge_threshold(db):
    p = start_probation(db, "REV-1", tenant_id="t1")
    _record(db, p, 29, agree=True)
    assert p.status == PROBATION_ACTIVE

    # 30th job is the first scheduled check.
    result = record_probation_job(db, p.id, "pass", "pass", tenant_id="t1", job_ref="JOB-30")
    assert result["check_due"] is True
    assert result["qualified_now"] is True
    assert result["gate"].qualified is True
    db.refresh(p)
    assert p.status == PROBATION_QUALIFIED
    assert p.qualified_at is not None


def test_at_30_below_threshold_stays_in_probation(db):
    p = start_probation(db, "REV-1", tenant_id="t1")
    # 26 agree, 4 disagree → 26/30 ≈ 0.867 < 0.90.
    _record(db, p, 26, agree=True, start=0)
    _record(db, p, 4, agree=False, start=26)
    db.refresh(p)
    assert p.jobs_recorded == 30
    assert p.status == PROBATION_ACTIVE
    gate = evaluate_gate(p)
    assert gate.min_sample_met is True
    assert gate.threshold_met is False
    assert gate.qualified is False


# ── Recheck cadence (§3.2) ────────────────────────────────────────────────────


def test_recheck_every_ten_jobs_after_minimum(db):
    p = start_probation(db, "REV-1", tenant_id="t1")
    # 27 agree + 3 disagree = 30 jobs, 90%? 27/30 = 0.90 exactly → qualifies.
    # Use 26/30 to stay under, then climb to 90% by job 40.
    _record(db, p, 26, agree=True, start=0)
    _record(db, p, 4, agree=False, start=26)
    db.refresh(p)
    assert p.status == PROBATION_ACTIVE

    # Jobs 31–39 are NOT check points even if the rate crosses 90%.
    _record(db, p, 9, agree=True, start=30)
    db.refresh(p)
    assert p.jobs_recorded == 39
    assert p.status == PROBATION_ACTIVE  # not a scheduled check

    # Job 40 is the next check: 26 + 4disagree + 9 + 1 = 36 agreements / 40 = 0.90.
    result = record_probation_job(db, p.id, "pass", "pass", tenant_id="t1", job_ref="JOB-40")
    assert result["check_due"] is True
    db.refresh(p)
    assert p.jobs_recorded == 40
    assert p.agreements == 36
    assert p.status == PROBATION_QUALIFIED


# ── Disagreement report (§3.2) ────────────────────────────────────────────────


def test_disagreement_report_has_per_point_detail(db):
    p = start_probation(db, "REV-1", tenant_id="t1")
    record_probation_job(
        db, p.id, "fail", "pass", tenant_id="t1", job_ref="J1",
        point_disagreements=[
            {"point_code": "PEARL_COUNT", "ai_verdict": "fail", "human_final_verdict": "pass"},
        ],
    )
    record_probation_job(
        db, p.id, "pass", "fail", tenant_id="t1", job_ref="J2",
        point_disagreements=[
            {"point_code": "PEARL_COUNT", "ai_verdict": "pass", "human_final_verdict": "fail"},
            {"point_code": "STAMEN", "ai_verdict": "pass", "human_final_verdict": "fail"},
        ],
    )
    record_probation_job(db, p.id, "pass", "pass", tenant_id="t1", job_ref="J3")  # agreed

    report = disagreement_report(db, p.id, tenant_id="t1")
    assert report["disagreements"] == 2  # J1 and J2, not J3
    points = {e["point_code"]: e["disagreement_count"] for e in report["detection_points"]}
    assert points == {"PEARL_COUNT": 2, "STAMEN": 1}
    # Ranked most-divergent first.
    assert report["detection_points"][0]["point_code"] == "PEARL_COUNT"


# ── Pause / resume (§3.2) ─────────────────────────────────────────────────────


def test_pause_blocks_recording_and_resume_restores(db):
    p = start_probation(db, "REV-1", tenant_id="t1")
    _record(db, p, 5, agree=True)

    pause_probation(db, p.id, tenant_id="t1")
    db.refresh(p)
    assert p.status == PROBATION_PAUSED
    assert p.paused_at is not None

    with pytest.raises(ProbationNotActive):
        record_probation_job(db, p.id, "pass", "pass", tenant_id="t1", job_ref="X")

    resume_probation(db, p.id, tenant_id="t1")
    db.refresh(p)
    assert p.status == PROBATION_ACTIVE
    # Counter preserved across pause/resume.
    assert p.jobs_recorded == 5


# ── Reset rule (§3.4) ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("field", ["expected_value", "pass_criteria"])
def test_edit_resets_on_judgment_fields(field):
    assert edit_resets_probation({field}) is True


@pytest.mark.parametrize("field", ["description", "regions", "regions_json"])
def test_edit_preserves_on_grounding_fields(field):
    assert edit_resets_probation({field}) is False


def test_reset_field_dominates_mixed_edit():
    assert edit_resets_probation({"description", "expected_value"}) is True


def test_new_revision_starts_counter_at_zero(db):
    p1 = start_probation(db, "REV-1", tenant_id="t1")
    _record(db, p1, 10, agree=True)
    db.refresh(p1)
    assert p1.jobs_recorded == 10

    # A reset edit produces a new standard_revision_id → fresh probation at 0.
    assert edit_resets_probation({"expected_value"})
    p2 = start_probation(db, "REV-2", tenant_id="t1")
    assert p2.id != p1.id
    assert p2.jobs_recorded == 0
    # Probation is keyed per revision.
    assert get_probation_for_revision(db, "REV-1", "t1").jobs_recorded == 10
    assert get_probation_for_revision(db, "REV-2", "t1").jobs_recorded == 0


# ── Guards ────────────────────────────────────────────────────────────────────


def test_duplicate_job_ref_rejected(db):
    p = start_probation(db, "REV-1", tenant_id="t1")
    record_probation_job(db, p.id, "pass", "pass", tenant_id="t1", job_ref="J1")
    with pytest.raises(InvalidProbationJob):
        record_probation_job(db, p.id, "pass", "pass", tenant_id="t1", job_ref="J1")


def test_start_probation_is_idempotent_per_revision(db):
    p1 = start_probation(db, "REV-1", tenant_id="t1")
    p2 = start_probation(db, "REV-1", tenant_id="t1")
    assert p1.id == p2.id


def test_invalid_thresholds_rejected(db):
    with pytest.raises(InvalidProbationState):
        start_probation(db, "REV-X", tenant_id="t1", agreement_threshold=1.5)
    with pytest.raises(InvalidProbationState):
        start_probation(db, "REV-Y", tenant_id="t1", min_sample_size=0)


def test_recording_after_qualified_is_rejected(db):
    p = start_probation(db, "REV-1", tenant_id="t1")
    _record(db, p, 30, agree=True)
    db.refresh(p)
    assert p.status == PROBATION_QUALIFIED
    with pytest.raises(ProbationNotActive):
        record_probation_job(db, p.id, "pass", "pass", tenant_id="t1", job_ref="EXTRA")
