"""QC checkpoint workflow tests.

Covers the 7 scenarios from PRD_QC_DB section 11.
All tests run against an in-memory SQLite database.
Vision model calls are replaced with deterministic mock observations
(clearly marked TEST_FIXTURE) — production code never fakes pass.
"""
import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker, Session

from src.db.models import Base
import src.db.qc_models  # noqa: F401
import src.db.qc_checkpoint_models  # noqa: F401
from src.db.qc_checkpoint_models import (
    QCProductSku, QCStandardVersion, QCCheckPoint, QCCheckRule,
    QCMediaAsset, QCStandardMedia, QCStandardIntake, QCOperatorConfirmation,
    QCInspectionJob, QCCheckpointResult, QCIncidentalFinding, QCAuditEvent,
)
from src.qc import intake_service, confirmation_service, standard_service, inspection_service


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db() -> Session:
    """In-memory SQLite session shared across all tests in this module."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def flower_sku(db) -> QCProductSku:
    return standard_service.create_sku(
        db,
        sku_code="FLOWER-BROOCH-001",
        product_name="Pearl Rhinestone Artificial Flower Brooch",
        category="artificial_flower_accessory",
    )


@pytest.fixture(scope="module")
def approved_standard(db, flower_sku) -> QCStandardVersion:
    """Approved standard v1.0 with 4 checkpoints (created directly for shared use)."""
    version = standard_service.create_standard_version(
        db,
        sku_id=flower_sku.id,
        version_no="v1.0",
        standard_name="Pearl Rhinestone Artificial Flower Brooch - v1.0",
        approved_by="test_operator",
    )

    cp_specs = [
        ("STAMEN_CENTERING", "Stamen Centering", "flower_center_stamen_cluster", "alignment", "major"),
        ("PEARL_COUNT", "Pearl Count", "stamen_pearls", "counting", "critical"),
        ("RHINESTONE_COUNT", "Rhinestone Count", "stamen_rhinestones", "counting", "critical"),
        ("PETAL_INTEGRITY", "Petal Integrity", "four_translucent_petals", "defect_detection", "critical"),
    ]
    for i, (code, name, part, method, severity) in enumerate(cp_specs, start=1):
        cp = QCCheckPoint(
            standard_version_id=version.id,
            checkpoint_code=code,
            checkpoint_name=name,
            target_part=part,
            inspection_method=method,
            severity=severity,
            display_order=i,
        )
        db.add(cp)
    db.commit()
    return version


def _get_checkpoints(db, standard_version_id) -> list[QCCheckPoint]:
    return (
        db.query(QCCheckPoint)
        .filter_by(standard_version_id=standard_version_id)
        .order_by(QCCheckPoint.display_order)
        .all()
    )


def _all_pass_observations(checkpoints) -> list[dict]:
    """TEST_FIXTURE: deterministic mock observations — all checkpoints pass."""
    obs_by_code = {
        "STAMEN_CENTERING": {
            "expected_json": {"offset_level": "none"},
            "observed_json": {
                "flower_silhouette_center": "320,240",
                "stamen_cluster_center": "321,241",
                "offset_direction": "none",
                "offset_level": "none",
            },
            "confidence_score": 0.97,
            "evidence_type": "keypoint",
        },
        "PEARL_COUNT": {
            "expected_json": {"pearl_count": 3},
            "observed_json": {"pearl_count": 3, "pearls_detected": [1, 2, 3]},
            "confidence_score": 0.99,
            "evidence_type": "count_result",
        },
        "RHINESTONE_COUNT": {
            "expected_json": {"rhinestone_count": 8},
            "observed_json": {"rhinestone_count": 8},
            "confidence_score": 0.98,
            "evidence_type": "count_result",
        },
        "PETAL_INTEGRITY": {
            "expected_json": {"all_petals": "intact"},
            "observed_json": {
                "petal_1_top_left": "pass",
                "petal_2_top_right": "pass",
                "petal_3_bottom_right": "pass",
                "petal_4_bottom_left": "pass",
            },
            "confidence_score": 0.96,
            "evidence_type": "bbox",
        },
    }
    results = []
    for cp in checkpoints:
        base = obs_by_code.get(cp.checkpoint_code, {})
        results.append({
            "checkpoint_id": cp.id,
            "checkpoint_code": cp.checkpoint_code,
            "checkpoint_name": cp.checkpoint_name,
            "result": "pass",
            "verification_status": "observed",
            **base,
        })
    return results


# ---------------------------------------------------------------------------
# 11.1 Standard Intake Test
# ---------------------------------------------------------------------------

def test_standard_intake(db, flower_sku):
    """Raw message saved, media saved, draft created, confirmation payload
    generated, approved standard NOT created before confirmation."""
    operator_text = (
        "Check stamen centering, pearl/rhinestone count, and petal cracks."
    )

    # 1. Create intake from raw message
    intake = intake_service.create_intake_from_message(
        db,
        sku_id=flower_sku.id,
        raw_text=operator_text,
        channel_type="web",
        operator_id="operator_1",
    )
    assert intake.id is not None
    assert intake.intake_status == "draft"
    assert intake.source_channel_message_id is not None

    # Raw message saved and preserved
    msg = intake.source_channel_message
    assert msg.raw_text == operator_text
    assert msg.channel_type == "web"

    # 2. Attach media asset
    asset = intake_service.attach_media_to_intake(
        db,
        storage_uri="file:///uploads/reference_front.jpg",
        media_type="image",
        media_role="standard_photo",
        sha256="abc123",
        uploaded_by="operator_1",
    )
    assert asset.id is not None
    assert asset.media_role == "standard_photo"

    # 3. Extract requirements into draft
    extracted = {
        "product_name": "Pearl Rhinestone Artificial Flower Brooch",
        "checkpoints": [
            {"code": "STAMEN_CENTERING", "name": "Stamen Centering",
             "severity": "major", "inspection_method": "alignment"},
            {"code": "PEARL_COUNT", "name": "Pearl Count",
             "severity": "critical", "inspection_method": "counting"},
            {"code": "RHINESTONE_COUNT", "name": "Rhinestone Count",
             "severity": "critical", "inspection_method": "counting"},
            {"code": "PETAL_INTEGRITY", "name": "Petal Integrity",
             "severity": "critical", "inspection_method": "defect_detection"},
        ],
    }
    intake = intake_service.extract_requirements(db, intake, extracted)
    assert intake.extracted_json is not None
    assert intake.intake_status == "extracted"

    # 4. Confirmation payload generated
    payload = intake_service.generate_confirmation_payload(intake)
    assert payload["intake_id"] == intake.id
    assert len(payload["checkpoints"]) == 4
    assert payload["status"] == "pending_operator_confirmation"

    # 5. Approved standard NOT created yet
    versions_before = (
        db.query(QCStandardVersion)
        .filter_by(sku_id=flower_sku.id, source_intake_id=intake.id)
        .count()
    )
    assert versions_before == 0, "Standard version must not be created before confirmation"

    # Mark pending
    intake = intake_service.mark_intake_pending_confirmation(db, intake)
    assert intake.intake_status == "pending_confirmation"


# ---------------------------------------------------------------------------
# 11.2 Operator Confirmation Test
# ---------------------------------------------------------------------------

def test_operator_confirmation(db, flower_sku):
    """Confirmation creates standard v1.0 with 4 approved checkpoints."""
    confirmed_json = {
        "product_name": "Pearl Rhinestone Artificial Flower Brooch",
        "checkpoints": [
            {
                "code": "STAMEN_CENTERING", "name": "Stamen Centering",
                "target_part": "flower_center_stamen_cluster",
                "inspection_method": "alignment", "severity": "major",
                "pass_rule_text": "Stamen cluster must be centered.",
                "check_rule": {
                    "rule_type": "position",
                    "expected_value_json": {"offset_level": "none"},
                },
            },
            {
                "code": "PEARL_COUNT", "name": "Pearl Count",
                "target_part": "stamen_pearls",
                "inspection_method": "counting", "severity": "critical",
                "pass_rule_text": "Exactly 3 pearls required.",
                "check_rule": {
                    "rule_type": "count",
                    "expected_value_json": {"pearl_count": 3},
                },
            },
            {
                "code": "RHINESTONE_COUNT", "name": "Rhinestone Count",
                "target_part": "stamen_rhinestones",
                "inspection_method": "counting", "severity": "critical",
                "pass_rule_text": "Exactly 8 rhinestones required.",
                "check_rule": {
                    "rule_type": "count",
                    "expected_value_json": {"rhinestone_count": 8},
                },
            },
            {
                "code": "PETAL_INTEGRITY", "name": "Petal Integrity",
                "target_part": "four_translucent_petals",
                "inspection_method": "defect_detection", "severity": "critical",
                "pass_rule_text": "No cracks or missing pieces.",
                "check_rule": {
                    "rule_type": "defect",
                    "expected_value_json": {"all_petals": "intact"},
                },
            },
        ],
    }

    # Create a fresh intake for this test
    intake = intake_service.create_intake_from_message(
        db,
        sku_id=flower_sku.id,
        raw_text="Confirm: pearl=3, rhinestone=8",
        operator_id="operator_2",
    )
    intake_service.extract_requirements(db, intake, confirmed_json)
    intake_service.mark_intake_pending_confirmation(db, intake)

    # Operator confirms with pearl=3, rhinestone=8
    confirmation = confirmation_service.confirm_standard_intake(
        db,
        intake=intake,
        confirmed_by="operator_2",
        confirmed_json=confirmed_json,
        operator_comment="Pearl count=3, rhinestone count=8 confirmed.",
    )
    assert confirmation.confirmation_status == "confirmed"
    assert confirmation.confirmed_by == "operator_2"

    # Standard version created from confirmed intake
    version = confirmation_service.create_standard_version_from_confirmed_intake(
        db,
        intake=intake,
        confirmation=confirmation,
        version_no="v1.0-confirm-test",
        standard_name="Flower Brooch QC Standard v1.0",
        approved_by="operator_2",
    )

    assert version.id is not None
    assert version.standard_status == "active"
    assert version.version_no == "v1.0-confirm-test"

    # 4 approved checkpoints created
    checkpoints = _get_checkpoints(db, version.id)
    assert len(checkpoints) == 4
    codes = {cp.checkpoint_code for cp in checkpoints}
    assert codes == {"STAMEN_CENTERING", "PEARL_COUNT", "RHINESTONE_COUNT", "PETAL_INTEGRITY"}

    # Standard is active
    db.refresh(version)
    assert version.standard_status == "active"

    # Cannot create from rejected confirmation
    rejected = confirmation_service.reject_standard_intake(
        db, intake=intake, confirmed_by="operator_2"
    )
    with pytest.raises(ValueError, match="confirmed"):
        confirmation_service.create_standard_version_from_confirmed_intake(
            db, intake=intake, confirmation=rejected
        )


# ---------------------------------------------------------------------------
# 11.3 Inspection Pass Test
# ---------------------------------------------------------------------------

def test_inspection_pass(db, flower_sku, approved_standard):
    """All 4 checkpoints pass → final_result=pass, coverage_rate=1.0."""
    job = inspection_service.create_inspection_job(
        db,
        sku_id=flower_sku.id,
        standard_version_id=approved_standard.id,
    )
    assert job.checkpoint_total == 4

    checkpoints = _get_checkpoints(db, approved_standard.id)
    observations = _all_pass_observations(checkpoints)

    inspection_service.save_checkpoint_results(db, inspection_job=job, results=observations)

    db.refresh(job)
    assert job.checkpoint_pass_count == 4
    assert job.checkpoint_fail_count == 0
    assert job.has_unchecked_checkpoint is False

    final = inspection_service.derive_final_result(db, job)
    assert final == "pass"

    db.refresh(job)
    assert job.coverage_rate == 1.0

    report = inspection_service.generate_final_report(db, job, final)
    assert report.final_result == "pass"
    assert report.report_status == "final"
    assert len(report.report_json["checkpoint_results"]) == 4


# ---------------------------------------------------------------------------
# 11.4 Inspection Fail Test
# ---------------------------------------------------------------------------

def test_inspection_fail(db, flower_sku, approved_standard):
    """STAMEN_CENTERING fails → final_result=fail."""
    job = inspection_service.create_inspection_job(
        db,
        sku_id=flower_sku.id,
        standard_version_id=approved_standard.id,
    )
    checkpoints = _get_checkpoints(db, approved_standard.id)
    observations = _all_pass_observations(checkpoints)

    # TEST_FIXTURE: override STAMEN_CENTERING to fail
    for obs in observations:
        if obs["checkpoint_code"] == "STAMEN_CENTERING":
            obs["result"] = "fail"
            obs["observed_json"] = {
                "flower_silhouette_center": "320,240",
                "stamen_cluster_center": "290,240",
                "offset_direction": "left",
                "offset_level": "obvious",
            }
            obs["failure_reason"] = "Stamen cluster obviously shifted left."
            break

    inspection_service.save_checkpoint_results(db, inspection_job=job, results=observations)

    db.refresh(job)
    stamen_result = (
        db.query(QCCheckpointResult)
        .filter_by(inspection_job_id=job.id, checkpoint_code="STAMEN_CENTERING")
        .one()
    )
    assert stamen_result.result == "fail"

    final = inspection_service.derive_final_result(db, job)
    assert final == "fail"


# ---------------------------------------------------------------------------
# 11.5 Review Required Test
# ---------------------------------------------------------------------------

def test_review_required_occluded_checkpoint(db, flower_sku, approved_standard):
    """PEARL_COUNT occluded → verification_status=occluded → final=review_required."""
    job = inspection_service.create_inspection_job(
        db,
        sku_id=flower_sku.id,
        standard_version_id=approved_standard.id,
    )
    checkpoints = _get_checkpoints(db, approved_standard.id)
    observations = _all_pass_observations(checkpoints)

    # TEST_FIXTURE: PEARL_COUNT cannot be confirmed — one pearl occluded
    for obs in observations:
        if obs["checkpoint_code"] == "PEARL_COUNT":
            obs["result"] = "review_required"
            obs["verification_status"] = "occluded"
            obs["observed_json"] = {"pearl_count": "unknown", "note": "one pearl obscured"}
            obs["confidence_score"] = 0.4
            obs["failure_reason"] = "Pearl count cannot be confirmed: one pearl is occluded."
            break

    inspection_service.save_checkpoint_results(db, inspection_job=job, results=observations)

    pearl_result = (
        db.query(QCCheckpointResult)
        .filter_by(inspection_job_id=job.id, checkpoint_code="PEARL_COUNT")
        .one()
    )
    assert pearl_result.result == "review_required"
    assert pearl_result.verification_status == "occluded"

    final = inspection_service.derive_final_result(db, job)
    assert final == "review_required"
    assert final != "pass"


# ---------------------------------------------------------------------------
# 11.6 Incidental Finding Test
# ---------------------------------------------------------------------------

def test_incidental_finding_triggers_review(db, flower_sku, approved_standard):
    """All checkpoints pass + major incidental finding → final=review_required."""
    job = inspection_service.create_inspection_job(
        db,
        sku_id=flower_sku.id,
        standard_version_id=approved_standard.id,
    )
    checkpoints = _get_checkpoints(db, approved_standard.id)
    observations = _all_pass_observations(checkpoints)
    inspection_service.save_checkpoint_results(db, inspection_job=job, results=observations)

    db.refresh(job)
    assert job.checkpoint_pass_count == 4

    # TEST_FIXTURE: incidental finding outside approved checklist
    findings = [
        {
            "finding_type": "color_abnormality",
            "target_part": "pearl",
            "finding_text": "Pearl color appears yellowish compared to approved white reference.",
            "severity": "major",
            "confidence_score": 0.83,
            "is_within_approved_checklist": False,
            "requires_human_review": True,
        }
    ]
    saved_findings = inspection_service.save_incidental_findings(
        db, inspection_job=job, findings=findings
    )
    assert len(saved_findings) == 1
    assert saved_findings[0].finding_type == "color_abnormality"
    assert saved_findings[0].is_within_approved_checklist is False

    db.refresh(job)
    assert job.major_incidental_finding_count == 1

    # Checkpoint results are still pass
    cp_results = (
        db.query(QCCheckpointResult)
        .filter_by(inspection_job_id=job.id)
        .all()
    )
    assert all(r.result == "pass" for r in cp_results)

    # But final result is review_required due to major incidental finding
    final = inspection_service.derive_final_result(db, job)
    assert final == "review_required"
    assert final != "pass"


# ---------------------------------------------------------------------------
# 11.7 No-Guess Policy Test
# ---------------------------------------------------------------------------

def test_no_guess_policy_missing_checkpoint(db, flower_sku, approved_standard):
    """3 of 4 checkpoints saved → has_unchecked_checkpoint=True → final != pass."""
    job = inspection_service.create_inspection_job(
        db,
        sku_id=flower_sku.id,
        standard_version_id=approved_standard.id,
    )
    assert job.checkpoint_total == 4

    checkpoints = _get_checkpoints(db, approved_standard.id)
    # TEST_FIXTURE: intentionally skip PETAL_INTEGRITY — no result provided
    observations = [
        obs for obs in _all_pass_observations(checkpoints)
        if obs["checkpoint_code"] != "PETAL_INTEGRITY"
    ]
    assert len(observations) == 3

    inspection_service.save_checkpoint_results(db, inspection_job=job, results=observations)

    db.refresh(job)
    assert job.has_unchecked_checkpoint is True
    assert job.coverage_rate < 1.0

    final = inspection_service.derive_final_result(db, job)
    assert final != "pass", "No-guess policy: missing checkpoint must not produce pass"
    assert final == "review_required"


# ---------------------------------------------------------------------------
# Schema integrity
# ---------------------------------------------------------------------------

def test_all_18_new_tables_exist(db):
    """Verify all 18 QC checkpoint tables are created."""
    inspector = inspect(db.get_bind())
    tables = set(inspector.get_table_names())
    expected = {
        "qc_product_sku",
        "qc_channel_message",
        "qc_media_asset",
        "qc_standard_intake",
        "qc_operator_confirmation",
        "qc_standard_version",
        "qc_standard_media",
        "qc_check_point",
        "qc_check_rule",
        "qc_inspection_job",
        "qc_inspection_media",
        "qc_model_result",
        "qc_checkpoint_result",
        "qc_incidental_finding",
        "qc_human_review",
        "qc_final_report",
        "qc_training_sample",
        "qc_audit_event",
    }
    missing = expected - tables
    assert not missing, f"Missing tables: {missing}"


def test_audit_events_written(db, flower_sku, approved_standard):
    """Audit events are written for standard version creation."""
    events = (
        db.query(QCAuditEvent)
        .filter_by(entity_type="qc_standard_version")
        .all()
    )
    assert len(events) > 0
    event_types = {e.event_type for e in events}
    assert "standard_version_created" in event_types
