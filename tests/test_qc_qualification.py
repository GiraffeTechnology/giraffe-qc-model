"""Qualification / shadow mode / accuracy gate tests (PR 27)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.sku_models  # noqa: F401
import src.db.qc_learning_models  # noqa: F401
import src.db.qc_authoring_models  # noqa: F401
import src.db.qc_source_models  # noqa: F401
import src.db.qc_sample_learning_models  # noqa: F401
import src.db.qc_readiness_models  # noqa: F401
import src.db.qc_production_models  # noqa: F401
import src.db.qc_qualification_models  # noqa: F401
from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearnedDetectionPointProposal
from src.db.qc_sample_learning_models import (
    QCConfirmedVisualRule,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
)
from src.db.qc_source_models import QCSourceDocument
from src.db.qc_production_models import (
    DISPOSITION_PASS,
    DISPOSITION_REJECT,
    DISPOSITION_REVIEW,
)
from src.qc_model.production.provider import (
    DetectionInspectionRequest,
    DetectionInspectionResult,
    ProductionInspectionProvider,
)
from src.qc_model.qualification import service
from src.qc_model.readiness.evaluator import evaluate_readiness

TP = "packQual"
T1 = "tenant_1"
T2 = "tenant_2"


def _uid() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _small_thresholds(monkeypatch):
    # Keep the sample-count minimums small so the passing path is testable
    # without huge fixtures. False-pass/false-fail thresholds keep their strict
    # defaults (0.0 / 0.05) so the accuracy gate is exercised for real.
    monkeypatch.setenv("QC_MIN_QUALIFICATION_SAMPLES_PER_POINT", "2")
    monkeypatch.setenv("QC_MIN_DEFECT_SAMPLES_PER_POINT", "1")
    monkeypatch.setenv("QC_MIN_BOUNDARY_SAMPLES_PER_POINT", "1")


class _LabelProvider(ProductionInspectionProvider):
    """Configured, production-eligible provider whose disposition is driven by the
    sample's ground-truth label encoded in the image reference.

    image ref convention: '...|predict=pass|...' etc. Defaults to a correct
    prediction so the qualification passes unless a sample injects a wrong one.
    """

    provider_name = "server_vlm"
    model_name = "qwen3.5-vl-8b-int4"
    production_eligible = True
    is_configured = True

    def inspect(self, request: DetectionInspectionRequest) -> DetectionInspectionResult:
        ref = request.image_references[0] if request.image_references else ""
        disposition = DISPOSITION_PASS
        if "predict=fail" in ref:
            disposition = DISPOSITION_REJECT
        elif "predict=review" in ref:
            disposition = DISPOSITION_REVIEW
        elif "predict=pass" in ref:
            disposition = DISPOSITION_PASS
        return DetectionInspectionResult(
            disposition=disposition, observed_features=["f"], evidence_regions=[{"bbox": [1, 2, 3, 4]}],
            confidence=0.9, provider=self.provider_name, model=self.model_name,
        )


def _pack_l2_ready(db, tenant=T1):
    db.add(QCSourceDocument(id=_uid(), tenant_id=tenant, training_pack_id=TP, source_type="process_spec", status="reviewed"))
    job = RuleAuthoringJob(id=_uid(), tenant_id=tenant, training_pack_id=TP, status="completed")
    db.add(job)
    db.flush()
    db.add(QCLearnedDetectionPointProposal(
        id=_uid(), tenant_id=tenant, rule_authoring_job_id=job.id, learning_job_id=None,
        proposed_code="dp", proposed_checkpoint_category="visual_defect",
        proposed_ai_role="primary_visual_judge", severity="major", status="approved", decision_rule="r",
    ))
    mjob = SampleLearningJob(id=_uid(), tenant_id=tenant, training_pack_id=TP, sample_group_id=_uid(),
                             status="completed", provider="qwen3.5-vl-8b-int4", model="m")
    db.add(mjob)
    db.flush()
    db.add(VisualRuleMemory(id=_uid(), tenant_id=tenant, sample_learning_job_id=mjob.id, training_pack_id=TP,
                            detection_point_code="dp", feature_type="defect_feature", status="applied"))
    for st in ("positive", "defect"):
        g = SampleGroup(id=_uid(), tenant_id=tenant, training_pack_id=TP, detection_point_id=_uid(),
                        detection_point_code="dp", sample_type=st, samples_json=[])
        db.add(g)
        db.flush()
        db.add(SampleLearningJob(id=_uid(), tenant_id=tenant, training_pack_id=TP, sample_group_id=g.id, status="completed"))
    db.add(QCConfirmedVisualRule(id=_uid(), tenant_id=tenant, training_pack_id=TP, detection_point_code="dp",
                                 feature_type="defect_feature", content_json={}, source_memory_id=_uid()))
    # L3 coverage minimums (reference/positive>=2/boundary) so only qualification blocks.
    import os
    for st in ("reference", "positive", "positive", "boundary"):
        g = SampleGroup(id=_uid(), tenant_id=tenant, training_pack_id=TP, detection_point_id=_uid(),
                        detection_point_code="dp", sample_type=st, samples_json=[])
        db.add(g)
        db.flush()
        db.add(SampleLearningJob(id=_uid(), tenant_id=tenant, training_pack_id=TP, sample_group_id=g.id, status="completed"))
    db.commit()


def _dataset_with_samples(db, tenant=T1, samples=None):
    ds = service.create_dataset(db, TP, tenant, name="qual1")
    for st, label, predict in (samples or []):
        service.add_sample(db, ds.id, "dp", st, f"s3://{_uid()}|predict={predict}", label, tenant)
    return ds


# ── Dataset + run metrics ────────────────────────────────────────────────────


def test_dataset_creation(db):
    _pack_l2_ready(db)
    ds = service.create_dataset(db, TP, T1, sku_id="sku1", name="q")
    assert ds.training_pack_id == TP


def test_qualification_run_metrics(db):
    _pack_l2_ready(db)
    # 2 pass (correct) + 1 defect predicted fail (correct) + 1 boundary pass.
    ds = _dataset_with_samples(db, samples=[
        ("positive", "pass", "pass"), ("reference", "pass", "pass"),
        ("defect", "fail", "fail"), ("boundary", "pass", "pass"),
    ])
    run = service.run_qualification(db, ds.id, T1, provider=_LabelProvider())
    assert run.status == "completed"
    results = service.list_results(db, run.id, T1)
    r = next(x for x in results if x.detection_point_code == "dp")
    assert r.false_pass == 0 and r.false_fail == 0
    assert r.meets_thresholds is True


def test_false_pass_blocks_controlled_active(db):
    _pack_l2_ready(db)
    # A defect sample the model wrongly predicts pass → false pass.
    ds = _dataset_with_samples(db, samples=[
        ("positive", "pass", "pass"),
        ("defect", "fail", "pass"),   # FALSE PASS
        ("boundary", "pass", "pass"),
    ])
    run = service.run_qualification(db, ds.id, T1, provider=_LabelProvider())
    r = next(x for x in service.list_results(db, run.id, T1) if x.detection_point_code == "dp")
    assert r.false_pass == 1
    assert r.false_pass_rate > 0.0
    assert r.meets_thresholds is False
    report = service.get_report_for_run(db, run.id, T1)
    assert report.overall_meets_thresholds is False
    # Cannot approve a failing report.
    with pytest.raises(service.InvalidApproval):
        service.approve_report(db, report.id, "approved", "sup1", T1)
    # Readiness controlled_active stays blocked.
    res = evaluate_readiness(db, TP, T1, target_mode="controlled_active")
    assert res.controlled_active_allowed is False
    assert "controlled_active_qualification" in res.to_dict()["blocking_checks"]


def test_false_fail_above_threshold_blocks(db, monkeypatch):
    _pack_l2_ready(db)
    monkeypatch.setenv("QC_MAX_FALSE_FAIL_RATE_L3", "0.0")  # no false fails allowed
    ds = _dataset_with_samples(db, samples=[
        ("positive", "pass", "fail"),   # FALSE FAIL
        ("defect", "fail", "fail"),
        ("boundary", "pass", "pass"),
    ])
    run = service.run_qualification(db, ds.id, T1, provider=_LabelProvider())
    r = next(x for x in service.list_results(db, run.id, T1) if x.detection_point_code == "dp")
    assert r.false_fail == 1
    assert r.meets_thresholds is False


def test_boundary_sample_evaluation(db):
    _pack_l2_ready(db)
    # Missing boundary samples → threshold failure recorded.
    import os
    os.environ["QC_MIN_BOUNDARY_SAMPLES_PER_POINT"] = "2"
    try:
        ds = _dataset_with_samples(db, samples=[
            ("positive", "pass", "pass"), ("defect", "fail", "fail"), ("boundary", "pass", "pass"),
        ])
        run = service.run_qualification(db, ds.id, T1, provider=_LabelProvider())
        r = next(x for x in service.list_results(db, run.id, T1) if x.detection_point_code == "dp")
        assert r.boundary_sample_count == 1
        assert any("boundary_samples" in f for f in r.threshold_failures_json)
        assert r.meets_thresholds is False
    finally:
        os.environ["QC_MIN_BOUNDARY_SAMPLES_PER_POINT"] = "1"


def test_per_detection_point_qualification(db):
    _pack_l2_ready(db)
    ds = service.create_dataset(db, TP, T1)
    # dp1 clean, dp2 has a false pass.
    for st, label, predict in [("positive", "pass", "pass"), ("defect", "fail", "fail"), ("boundary", "pass", "pass")]:
        service.add_sample(db, ds.id, "dp1", st, f"s3://{_uid()}|predict={predict}", label, T1)
    for st, label, predict in [("positive", "pass", "pass"), ("defect", "fail", "pass"), ("boundary", "pass", "pass")]:
        service.add_sample(db, ds.id, "dp2", st, f"s3://{_uid()}|predict={predict}", label, T1)
    run = service.run_qualification(db, ds.id, T1, provider=_LabelProvider())
    results = {x.detection_point_code: x for x in service.list_results(db, run.id, T1)}
    assert results["dp1"].meets_thresholds is True
    assert results["dp2"].meets_thresholds is False


# ── Approval, immutability, and unlocking L3 ─────────────────────────────────


def test_supervisor_approval_required_and_unlocks_l3(db):
    _pack_l2_ready(db)
    ds = _dataset_with_samples(db, samples=[
        ("positive", "pass", "pass"), ("reference", "pass", "pass"),
        ("defect", "fail", "fail"), ("boundary", "pass", "pass"),
    ])
    run = service.run_qualification(db, ds.id, T1, provider=_LabelProvider())
    report = service.get_report_for_run(db, run.id, T1)
    assert report.overall_meets_thresholds is True
    # Before approval, L3 is still blocked.
    assert evaluate_readiness(db, TP, T1, target_mode="controlled_active").controlled_active_allowed is False
    # Approval requires an identity.
    with pytest.raises(service.InvalidApproval):
        service.approve_report(db, report.id, "approved", "  ", T1)
    service.approve_report(db, report.id, "approved", "supervisor_1", T1, "meets thresholds")
    # Now controlled_active is unlocked.
    res = evaluate_readiness(db, TP, T1, target_mode="controlled_active")
    assert res.controlled_active_allowed is True


def test_report_immutable_after_approval(db):
    _pack_l2_ready(db)
    ds = _dataset_with_samples(db, samples=[
        ("positive", "pass", "pass"), ("defect", "fail", "fail"), ("boundary", "pass", "pass"),
    ])
    run = service.run_qualification(db, ds.id, T1, provider=_LabelProvider())
    report = service.get_report_for_run(db, run.id, T1)
    service.approve_report(db, report.id, "approved", "sup1", T1)
    with pytest.raises(service.ReportImmutable):
        service.approve_report(db, report.id, "approved", "sup2", T1)


# ── Shadow mode ──────────────────────────────────────────────────────────────


def test_shadow_mode_records_disagreement(db):
    _pack_l2_ready(db)
    service.record_shadow_observation(db, TP, DISPOSITION_PASS, "pass", T1, detection_point_code="dp")
    service.record_shadow_observation(db, TP, DISPOSITION_PASS, "fail", T1, detection_point_code="dp")
    rep = service.shadow_report(db, TP, T1)
    assert rep["observations"] == 2
    assert rep["disagreements"] == 1
    assert rep["disagreement_rate"] == 0.5


def test_shadow_mode_does_not_affect_readiness(db):
    _pack_l2_ready(db)
    # Recording shadow observations must not unlock L3.
    for _ in range(5):
        service.record_shadow_observation(db, TP, DISPOSITION_PASS, "pass", T1, detection_point_code="dp")
    assert evaluate_readiness(db, TP, T1, target_mode="controlled_active").controlled_active_allowed is False


# ── Provider eligibility + tenant isolation ──────────────────────────────────


def test_qualification_requires_production_eligible_provider(db):
    _pack_l2_ready(db)
    ds = _dataset_with_samples(db, samples=[("defect", "fail", "fail")])

    class _Mock(_LabelProvider):
        provider_name = "mock_vlm"
        production_eligible = False

    with pytest.raises(service.ProviderNotEligible):
        service.run_qualification(db, ds.id, T1, provider=_Mock())


def test_cross_tenant_dataset_create_rejected(db):
    _pack_l2_ready(db, tenant=T1)
    from src.qc_model.training_pack.ownership import CrossTenantTrainingPack
    with pytest.raises(CrossTenantTrainingPack):
        service.create_dataset(db, TP, T2)


def test_approved_qualification_is_tenant_scoped(db):
    _pack_l2_ready(db, tenant=T1)
    ds = _dataset_with_samples(db, tenant=T1, samples=[
        ("positive", "pass", "pass"), ("defect", "fail", "fail"), ("boundary", "pass", "pass"),
    ])
    run = service.run_qualification(db, ds.id, T1, provider=_LabelProvider())
    report = service.get_report_for_run(db, run.id, T1)
    service.approve_report(db, report.id, "approved", "sup1", T1)
    assert service.has_approved_qualification(db, TP, T1) is True
    assert service.has_approved_qualification(db, TP, T2) is False
