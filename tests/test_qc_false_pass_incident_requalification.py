"""False-pass incident response & requalification loop tests (PR 28)."""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
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
import src.db.qc_incident_models  # noqa: F401
from src.api.deps import get_db_dep
from src.api.main import app
from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearnedDetectionPointProposal
from src.db.qc_sample_learning_models import (
    QCConfirmedVisualRule,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
)
from src.db.qc_source_models import QCSourceDocument
from src.db.qc_incident_models import (
    QCIncidentAuditEvent,
    QCRequalificationRequirement,
    QCScopeSuspension,
)
from src.db.qc_qualification_models import QualificationReport, REPORT_APPROVED
from src.db.qc_production_models import DISPOSITION_PASS, DISPOSITION_REJECT
from src.qc_model.production.provider import (
    DetectionInspectionRequest,
    DetectionInspectionResult,
    ProductionInspectionProvider,
)
from src.qc_model.qualification import service as qual_service
from src.qc_model.incident import service
from src.qc_model.readiness.evaluator import evaluate_readiness

TP = "packInc"
T1 = "tenant_1"
T2 = "tenant_2"


def _uid() -> str:
    return uuid.uuid4().hex


@pytest.fixture(autouse=True)
def _small_thresholds(monkeypatch):
    monkeypatch.setenv("QC_MIN_QUALIFICATION_SAMPLES_PER_POINT", "2")
    monkeypatch.setenv("QC_MIN_DEFECT_SAMPLES_PER_POINT", "1")
    monkeypatch.setenv("QC_MIN_BOUNDARY_SAMPLES_PER_POINT", "1")


class _LabelProvider(ProductionInspectionProvider):
    provider_name = "server_vlm"
    model_name = "qwen3.5-vl-8b-int4"
    production_eligible = True
    is_configured = True

    def inspect(self, request: DetectionInspectionRequest) -> DetectionInspectionResult:
        ref = request.image_references[0] if request.image_references else ""
        disposition = DISPOSITION_REJECT if "predict=fail" in ref else DISPOSITION_PASS
        return DetectionInspectionResult(disposition=disposition, observed_features=["f"],
                                         evidence_regions=[{"bbox": [1, 2, 3, 4]}], confidence=0.9,
                                         provider=self.provider_name, model=self.model_name)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_db_dep] = override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _l2_ready(db, tenant=T1):
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
    db.add(QCConfirmedVisualRule(id=_uid(), tenant_id=tenant, training_pack_id=TP, detection_point_code="dp",
                                 feature_type="defect_feature", content_json={}, source_memory_id=_uid()))
    for st in ("reference", "positive", "positive", "defect", "boundary"):
        g = SampleGroup(id=_uid(), tenant_id=tenant, training_pack_id=TP, detection_point_id=_uid(),
                        detection_point_code="dp", sample_type=st, samples_json=[])
        db.add(g)
        db.flush()
        db.add(SampleLearningJob(id=_uid(), tenant_id=tenant, training_pack_id=TP, sample_group_id=g.id, status="completed"))
    db.commit()


def _qualify(db, tenant=T1, provider=None, all_correct=True):
    """Create + run + approve a passing qualification report; returns it."""
    ds = qual_service.create_dataset(db, TP, tenant)
    samples = [("positive", "pass", "pass"), ("reference", "pass", "pass"),
               ("defect", "fail", "fail"), ("boundary", "pass", "pass")]
    if not all_correct:
        samples = [("positive", "pass", "pass"), ("defect", "fail", "pass"), ("boundary", "pass", "pass")]
    for st, label, predict in samples:
        qual_service.add_sample(db, ds.id, "dp", st, f"s3://{_uid()}|predict={predict}", label, tenant)
    run = qual_service.run_qualification(db, ds.id, tenant, provider=provider or _LabelProvider())
    report = qual_service.get_report_for_run(db, run.id, tenant)
    if report.overall_meets_thresholds:
        qual_service.approve_report(db, report.id, "approved", "sup1", tenant)
    return report


def _make_l3_ready(db, tenant=T1):
    _l2_ready(db, tenant)
    _qualify(db, tenant)
    res = evaluate_readiness(db, TP, tenant, target_mode="controlled_active")
    assert res.controlled_active_allowed is True
    return res


# ── Report + confirm + suspend ───────────────────────────────────────────────


def test_report_creates_p0_incident(db):
    _l2_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    assert inc.severity == "P0"
    assert inc.status == "triage_pending"
    assert db.query(QCIncidentAuditEvent).filter_by(incident_id=inc.id).count() == 1


def test_confirm_creates_suspension_and_requalification(db):
    _make_l3_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="downstream defect")
    suspensions = service.active_l3_suspensions_for_pack(db, TP, T1)
    assert len(suspensions) == 1
    bundle = service.get_incident_bundle(db, inc.id, T1)
    assert len(bundle["requalification_requirements"]) == 1
    assert bundle["requalification_requirements"][0].status == "required"


def test_confirmed_false_pass_blocks_controlled_active(db):
    _make_l3_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    res = evaluate_readiness(db, TP, T1, target_mode="controlled_active")
    assert res.controlled_active_allowed is False
    assert "active_false_pass_suspension" in res.to_dict()["blocking_checks"]
    check = next(c for c in res.to_dict()["checks"] if c["id"] == "active_false_pass_suspension")
    assert check["severity"] == "P0"
    assert check["blocking_items"]


def test_l2_remains_available_after_l3_suspension(db):
    _make_l3_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    res = evaluate_readiness(db, TP, T1, target_mode="production_assisted")
    assert res.production_assisted_allowed is True


def test_rejected_report_does_not_suspend(db):
    _make_l3_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, reported_by="qc1")
    service.confirm_incident(db, inc.id, "rejected_not_false_pass", "sup1", T1, confirmation_reason="not a defect")
    assert service.active_l3_suspensions_for_pack(db, TP, T1) == []
    assert evaluate_readiness(db, TP, T1, target_mode="controlled_active").controlled_active_allowed is True


def test_ambiguous_scope_suspends_broader_scope(db):
    _make_l3_ready(db)
    # No sku/station/detection_point → pack-level (broader) scope.
    inc = service.report_incident(db, TP, "false_pass", T1, reported_by="qc1")
    assert inc.affected_scope_json["granularity"] == "training_pack"
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    s = service.active_l3_suspensions_for_pack(db, TP, T1)[0]
    assert s.scope_json["granularity"] == "training_pack"


# ── Lift rules ───────────────────────────────────────────────────────────────


def _confirmed_incident(db):
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    return inc, service.active_l3_suspensions_for_pack(db, TP, T1)[0]


def test_old_report_cannot_lift(db):
    _make_l3_ready(db)
    # Grab the pre-incident approved report id.
    pre = db.query(QualificationReport).filter_by(training_pack_id=TP, tenant_id=T1, status=REPORT_APPROVED).first()
    inc, suspension = _confirmed_incident(db)
    with pytest.raises(service.InvalidLift):
        service.lift_suspension(db, suspension.id, "sup1", pre.id, T1, lift_reason="try old")


def test_no_report_cannot_lift(db):
    _make_l3_ready(db)
    inc, suspension = _confirmed_incident(db)
    with pytest.raises(service.InvalidLift):
        service.lift_suspension(db, suspension.id, "sup1", "", T1, lift_reason="no report")


def test_unapproved_report_cannot_lift(db):
    _make_l3_ready(db)
    inc, suspension = _confirmed_incident(db)
    # New run but NOT approved.
    ds = qual_service.create_dataset(db, TP, T1)
    for st, label, predict in [("positive", "pass", "pass"), ("defect", "fail", "fail"), ("boundary", "pass", "pass")]:
        qual_service.add_sample(db, ds.id, "dp", st, f"s3://{_uid()}|predict={predict}", label, T1)
    run = qual_service.run_qualification(db, ds.id, T1, provider=_LabelProvider())
    report = qual_service.get_report_for_run(db, run.id, T1)  # draft, not approved
    with pytest.raises(service.InvalidLift):
        service.lift_suspension(db, suspension.id, "sup1", report.id, T1, lift_reason="unapproved")


def test_failing_report_cannot_lift(db):
    _make_l3_ready(db)
    inc, suspension = _confirmed_incident(db)
    failing = _qualify(db, T1, all_correct=False)  # has a false pass → not approvable
    assert failing.overall_meets_thresholds is False
    with pytest.raises(service.InvalidLift):
        service.lift_suspension(db, suspension.id, "sup1", failing.id, T1, lift_reason="failing")


def test_mock_provider_report_cannot_lift(db):
    from src.db.qc_qualification_models import QualificationRun
    _make_l3_ready(db)
    inc, suspension = _confirmed_incident(db)
    # A new approved passing report, but produced by a non-production-eligible
    # provider (the lift guard must reject it even though it is approved+passing).
    report = _qualify(db, T1)
    run = db.query(QualificationRun).filter_by(id=report.run_id, tenant_id=T1).first()
    run.provider = "mock_vlm"
    db.commit()
    with pytest.raises(service.InvalidLift):
        service.lift_suspension(db, suspension.id, "sup1", report.id, T1, lift_reason="mock")


def test_new_passing_report_lifts_and_restores_l3(db):
    _make_l3_ready(db)
    inc, suspension = _confirmed_incident(db)
    # New approved passing report created AFTER confirmation, production-eligible.
    new_report = _qualify(db, T1)
    lifted = service.lift_suspension(db, suspension.id, "qm1", new_report.id, T1, lift_reason="requalified")
    assert lifted.status == "lifted"
    # Requalification requirement satisfied.
    bundle = service.get_incident_bundle(db, inc.id, T1)
    assert bundle["requalification_requirements"][0].status == "satisfied"
    # L3 restored.
    assert evaluate_readiness(db, TP, T1, target_mode="controlled_active").controlled_active_allowed is True


# ── Audit + tenant isolation + no autonomous decision ────────────────────────


def test_audit_events_append_only(db):
    _make_l3_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    n1 = db.query(QCIncidentAuditEvent).filter_by(incident_id=inc.id).count()
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    n2 = db.query(QCIncidentAuditEvent).filter_by(incident_id=inc.id).count()
    # confirm appends incident_confirmed + suspension_created + requalification_required.
    assert n2 >= n1 + 3


def test_tenant_isolation_incident(db):
    _l2_ready(db, tenant=T1)
    inc = service.report_incident(db, TP, "false_pass", T1, reported_by="qc1")
    with pytest.raises(service.IncidentNotFound):
        service.get_incident(db, inc.id, T2)
    with pytest.raises(service.IncidentNotFound):
        service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T2, confirmation_reason="r")


def test_tenant_isolation_suspension_lift(db):
    _make_l3_ready(db, tenant=T1)
    inc, suspension = _confirmed_incident(db)
    with pytest.raises(service.SuspensionNotFound):
        service.lift_suspension(db, suspension.id, "sup1", "any", T2, lift_reason="x")


def test_confirm_does_not_create_production_final_decision(db):
    # No autonomous pass/reject: the incident flow never writes a production
    # final decision or detection result.
    from src.db.qc_production_models import HumanFinalDecision, ProductionDetectionResult
    _make_l3_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    assert db.query(HumanFinalDecision).count() == 0
    assert db.query(ProductionDetectionResult).count() == 0


# ── API + readiness + UI ─────────────────────────────────────────────────────


def test_api_incident_flow(client, db):
    _make_l3_ready(db)
    r = client.post("/api/qc/incidents", json={"training_pack_id": TP, "tenant_id": T1,
                                               "detection_point_code": "dp", "reported_by": "qc1"})
    assert r.status_code == 201
    iid = r.json()["incident_id"]
    assert r.json()["severity"] == "P0"
    c = client.post(f"/api/qc/incidents/{iid}/confirmation",
                    json={"confirmation_decision": "confirmed_false_pass", "confirmed_by": "sup1",
                          "tenant_id": T1, "confirmation_reason": "r"})
    assert c.status_code == 201
    # Readiness endpoint now blocks controlled_active with the suspension item.
    data = client.get(f"/api/qc/training-packs/{TP}/readiness?tenant_id={T1}&target_mode=controlled_active").json()
    assert data["controlled_active_allowed"] is False
    assert "active_false_pass_suspension" in data["blocking_checks"]


def test_api_confirm_requires_identity(client, db):
    _l2_ready(db)
    iid = client.post("/api/qc/incidents", json={"training_pack_id": TP, "tenant_id": T1, "reported_by": "qc1"}).json()["incident_id"]
    r = client.post(f"/api/qc/incidents/{iid}/confirmation",
                    json={"confirmation_decision": "confirmed_false_pass", "confirmed_by": "", "tenant_id": T1, "confirmation_reason": "r"})
    assert r.status_code == 422


# ── P1: requalification must cover the suspended scope ───────────────────────


def _qualify_for_dp(db, dp, tenant=T1, sku_id=None, station_id=None):
    ds = qual_service.create_dataset(db, TP, tenant, sku_id=sku_id, station_id=station_id)
    for st, label, predict in [("positive", "pass", "pass"), ("defect", "fail", "fail"), ("boundary", "pass", "pass")]:
        qual_service.add_sample(db, ds.id, dp, st, f"s3://{_uid()}|predict={predict}", label, tenant)
    run = qual_service.run_qualification(db, ds.id, tenant, provider=_LabelProvider())
    report = qual_service.get_report_for_run(db, run.id, tenant)
    qual_service.approve_report(db, report.id, "approved", "sup1", tenant)
    return report


def test_report_for_other_detection_point_cannot_lift(db):
    _make_l3_ready(db)
    inc, suspension = _confirmed_incident(db)   # suspension scoped to detection point "dp"
    # A new approved passing report that only covers a DIFFERENT detection point.
    wrong = _qualify_for_dp(db, "dp_other")
    assert wrong.qualified_detection_point_codes_json == ["dp_other"]
    with pytest.raises(service.InvalidLift):
        service.lift_suspension(db, suspension.id, "sup1", wrong.id, T1, lift_reason="wrong dp")
    # Suspension is still active.
    assert service.get_suspension(db, suspension.id, T1).status == "active"


def test_report_covering_detection_point_lifts(db):
    _make_l3_ready(db)
    inc, suspension = _confirmed_incident(db)   # scoped to "dp"
    covering = _qualify_for_dp(db, "dp")
    lifted = service.lift_suspension(db, suspension.id, "sup1", covering.id, T1, lift_reason="requalified dp")
    assert lifted.status == "lifted"


def test_report_for_other_sku_cannot_lift(db):
    _make_l3_ready(db)
    # Incident scoped to a specific SKU.
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp",
                                  sku_id="sku_a", reported_by="qc1")
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    suspension = service.active_l3_suspensions_for_pack(db, TP, T1)[0]
    assert suspension.sku_id == "sku_a"
    # Requalification for dp but from a dataset with a different SKU.
    wrong_sku = _qualify_for_dp(db, "dp", sku_id="sku_b")
    with pytest.raises(service.InvalidLift):
        service.lift_suspension(db, suspension.id, "sup1", wrong_sku.id, T1, lift_reason="wrong sku")
    # Correct SKU + DP lifts.
    right = _qualify_for_dp(db, "dp", sku_id="sku_a")
    assert service.lift_suspension(db, suspension.id, "sup1", right.id, T1, lift_reason="ok").status == "lifted"


# ── P2: duplicate confirmation is idempotent / terminal ──────────────────────


def test_duplicate_confirmation_is_idempotent(db):
    _make_l3_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    # Retry / double submit.
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r again")
    active = db.query(QCScopeSuspension).filter_by(incident_id=inc.id, status="active").all()
    assert len(active) == 1
    requals = db.query(QCRequalificationRequirement).filter_by(incident_id=inc.id).all()
    assert len(requals) == 1


def test_confirmed_incident_cannot_be_flipped(db):
    _make_l3_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    with pytest.raises(service.InvalidConfirmation):
        service.confirm_incident(db, inc.id, "rejected_not_false_pass", "sup1", T1, confirmation_reason="flip")


def test_ui_incident_page_smoke(client, db):
    _make_l3_ready(db)
    inc = service.report_incident(db, TP, "false_pass", T1, detection_point_code="dp", reported_by="qc1")
    service.confirm_incident(db, inc.id, "confirmed_false_pass", "sup1", T1, confirmation_reason="r")
    page = client.get(f"/admin/qc-model/incidents/{inc.id}?tenant_id={T1}")
    assert page.status_code == 200
    assert "False-Pass Incident Response" in page.text
    assert "Audit trail" in page.text
