"""Production Assisted Mode tests (PR 25)."""
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
from src.api.deps import get_db_dep
from src.api.main import app
from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearnedDetectionPointProposal
from src.db.qc_production_models import HumanFinalDecision, ProductionInspectionRun
from src.db.qc_sample_learning_models import (
    QCConfirmedVisualRule,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
)
from src.db.qc_source_models import QCSourceDocument
from src.qc_model.production import service
from src.qc_model.production.provider import (
    DetectionInspectionRequest,
    DetectionInspectionResult,
    ProductionInspectionProvider,
)
from src.db.qc_production_models import DISPOSITION_PASS, DISPOSITION_REVIEW


TP = "packProd"
T1 = "tenant_1"
T2 = "tenant_2"


def _uid() -> str:
    return uuid.uuid4().hex


# ── Eligible + ineligible test providers ────────────────────────────────────


class _EligibleProvider(ProductionInspectionProvider):
    provider_name = "server_vlm_eval"  # not mock/fake/stub/skeleton/deterministic/test
    model_name = "qwen3.5-vl-8b-int4"
    production_eligible = True

    def __init__(self, disposition=DISPOSITION_PASS, evidence=None):
        self._disposition = disposition
        self._evidence = [{"bbox": [1, 2, 3, 4]}] if evidence is None else evidence

    def inspect(self, request: DetectionInspectionRequest) -> DetectionInspectionResult:
        return DetectionInspectionResult(
            disposition=self._disposition,
            observed_features=["f"], normal_features_matched=["f"],
            evidence_regions=self._evidence, confidence=0.9, uncertainty="",
        )


class _IneligibleProvider(_EligibleProvider):
    provider_name = "mock_vlm"
    production_eligible = False


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@pytest.fixture
def db(session_factory):
    s = session_factory()
    yield s
    s.close()


@pytest.fixture
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


# ── Readiness fixtures (mirror the PR24 L2-ready shape) ──────────────────────


def _confirmed_rule(db, tenant=T1, code="dp", feature="defect_feature", content=None):
    db.add(QCConfirmedVisualRule(
        id=_uid(), tenant_id=tenant, training_pack_id=TP, detection_point_code=code,
        feature_type=feature, content_json=content or {}, source_memory_id=_uid(),
    ))
    db.commit()


def _l2_ready(db, tenant=T1, confirmed_content=None):
    db.add(QCSourceDocument(id=_uid(), tenant_id=tenant, training_pack_id=TP, source_type="process_spec", status="reviewed"))
    job = RuleAuthoringJob(id=_uid(), tenant_id=tenant, training_pack_id=TP, status="completed")
    db.add(job)
    db.flush()
    db.add(QCLearnedDetectionPointProposal(
        id=_uid(), tenant_id=tenant, rule_authoring_job_id=job.id, learning_job_id=None,
        proposed_code="dp", proposed_checkpoint_category="visual_defect",
        proposed_ai_role="primary_visual_judge", severity="major", status="approved", decision_rule="r",
    ))
    # approved memory + production-eligible provider job
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
    _confirmed_rule(db, tenant, content=confirmed_content)
    db.commit()


def _session_with_capture(db, tenant=T1):
    s = service.create_session(db, TP, tenant, sku_id="sku1", station_id="st1", operator_id="op1")
    service.add_capture(db, s.id, "s3://img.jpg", tenant, {"lighting": "ok"})
    return s


# ── Tests ────────────────────────────────────────────────────────────────────


def test_cannot_start_session_when_readiness_fails(db):
    # Pack known (source only) but not L2-ready.
    db.add(QCSourceDocument(id=_uid(), tenant_id=T1, training_pack_id=TP, source_type="process_spec", status="reviewed"))
    db.commit()
    with pytest.raises(service.ReadinessNotMet):
        service.create_session(db, TP, T1)


def test_can_start_session_when_l2_ready(db):
    _l2_ready(db)
    s = service.create_session(db, TP, T1, operator_id="op1")
    assert s.status == "open"
    assert s.production_mode == "production_assisted"


def test_run_produces_evidence_packet(db):
    _l2_ready(db)
    s = _session_with_capture(db)
    run = service.run_inspection(db, s.id, T1, provider=_EligibleProvider())
    assert run.status == "completed"
    assert run.detection_result_count >= 1
    packet = service.get_evidence_packet(db, run.id, T1)
    assert packet is not None
    assert packet.packet_json["human_final_decision_required"] is True
    results = service.list_detection_results(db, run.id, T1)
    # Provenance links present.
    assert all(r.provider == "server_vlm_eval" and r.prompt_schema_version for r in results)
    assert any(r.confirmed_visual_rule_id for r in results)


def test_run_is_not_a_final_decision(db):
    _l2_ready(db)
    s = _session_with_capture(db)
    run = service.run_inspection(db, s.id, T1, provider=_EligibleProvider())
    # No HumanFinalDecision exists just because a run completed.
    assert db.query(HumanFinalDecision).filter_by(run_id=run.id).count() == 0
    # overall disposition is a recommendation, not a final pass/reject.
    assert run.overall_disposition == DISPOSITION_PASS


def test_final_decision_requires_identity(db):
    _l2_ready(db)
    s = _session_with_capture(db)
    run = service.run_inspection(db, s.id, T1, provider=_EligibleProvider())
    with pytest.raises(service.InvalidFinalDecision):
        service.record_final_decision(db, run.id, "pass", "  ", T1)
    rec = service.record_final_decision(db, run.id, "pass", "supervisor_1", T1, "looks good")
    assert rec.decided_by == "supervisor_1"
    assert rec.recommended_disposition == DISPOSITION_PASS


def test_missing_evidence_forces_review(db):
    # Confirmed rule requires evidence; provider returns none → pass downgraded.
    _l2_ready(db, confirmed_content={"evidence_required": ["seam close-up"]})
    s = _session_with_capture(db)
    run = service.run_inspection(db, s.id, T1, provider=_EligibleProvider(disposition=DISPOSITION_PASS, evidence=[]))
    results = service.list_detection_results(db, run.id, T1)
    visual = [r for r in results if r.checkpoint_category == "visual"]
    assert visual and all(r.disposition == DISPOSITION_REVIEW for r in visual)


def test_physical_measurement_forces_measurement_required(db):
    _l2_ready(db)
    # Add an approved physical-measurement detection point.
    job = RuleAuthoringJob(id=_uid(), tenant_id=T1, training_pack_id=TP, status="completed")
    db.add(job)
    db.flush()
    db.add(QCLearnedDetectionPointProposal(
        id=_uid(), tenant_id=T1, rule_authoring_job_id=job.id, learning_job_id=None,
        proposed_code="width", proposed_checkpoint_category="physical_measurement",
        proposed_ai_role="record_only", severity="major", status="approved", decision_rule="caliper",
    ))
    db.commit()
    s = _session_with_capture(db)
    run = service.run_inspection(db, s.id, T1, provider=_EligibleProvider())
    results = service.list_detection_results(db, run.id, T1)
    phys = [r for r in results if r.detection_point_code == "width"]
    assert phys and phys[0].disposition == "measurement_required"


def test_mock_provider_cannot_run_in_production_assisted(db):
    _l2_ready(db)
    s = _session_with_capture(db)
    with pytest.raises(service.ProviderNotEligible):
        service.run_inspection(db, s.id, T1, provider=_IneligibleProvider())


def test_default_provider_is_not_production_eligible(db):
    _l2_ready(db)
    s = _session_with_capture(db)
    # No provider passed → default mock provider → fail closed.
    with pytest.raises(service.ProviderNotEligible):
        service.run_inspection(db, s.id, T1)


def test_run_requires_capture(db):
    _l2_ready(db)
    s = service.create_session(db, TP, T1)
    with pytest.raises(service.NoCaptures):
        service.run_inspection(db, s.id, T1, provider=_EligibleProvider())


def test_tenant_isolation_session(db):
    _l2_ready(db, tenant=T1)
    s = service.create_session(db, TP, T1)
    with pytest.raises(service.SessionNotFound):
        service.get_session(db, s.id, T2)


def test_cross_tenant_session_create_rejected(db):
    _l2_ready(db, tenant=T1)  # binds TP to T1
    from src.qc_model.training_pack.ownership import CrossTenantTrainingPack
    with pytest.raises(CrossTenantTrainingPack):
        service.create_session(db, TP, T2)


# ── API + UI ─────────────────────────────────────────────────────────────────


def test_api_session_flow_and_final_decision(client, db):
    _l2_ready(db)
    r = client.post("/api/qc/production/inspection-sessions",
                    json={"training_pack_id": TP, "tenant_id": T1, "operator_id": "op1"})
    assert r.status_code == 201
    sid = r.json()["session_id"]
    assert client.post(f"/api/qc/production/inspection-sessions/{sid}/captures",
                       json={"image_reference": "s3://a.jpg", "tenant_id": T1}).status_code == 201
    # Default (mock) provider → run fails closed with 422.
    assert client.post(f"/api/qc/production/inspection-sessions/{sid}/run",
                       json={"tenant_id": T1}).status_code == 422


def test_api_readiness_gate_returns_409(client, db):
    db.add(QCSourceDocument(id=_uid(), tenant_id=T1, training_pack_id=TP, source_type="process_spec", status="reviewed"))
    db.commit()
    r = client.post("/api/qc/production/inspection-sessions",
                    json={"training_pack_id": TP, "tenant_id": T1})
    assert r.status_code == 409


def test_api_final_decision_requires_identity(client, db):
    _l2_ready(db)
    s = _session_with_capture(db)
    run = service.run_inspection(db, s.id, T1, provider=_EligibleProvider())
    r = client.post(f"/api/qc/production/inspection-runs/{run.id}/final-decision",
                    json={"decision": "pass", "decided_by": "", "tenant_id": T1})
    assert r.status_code == 422


def test_ui_production_session_smoke(client, db):
    _l2_ready(db)
    s = _session_with_capture(db)
    service.run_inspection(db, s.id, T1, provider=_EligibleProvider())
    page = client.get(f"/admin/qc-model/production/sessions/{s.id}?tenant_id={T1}")
    assert page.status_code == 200
    assert "Production Assisted Mode" in page.text
    assert "Human final decision" in page.text
