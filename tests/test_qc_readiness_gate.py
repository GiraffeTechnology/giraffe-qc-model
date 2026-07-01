"""Training Pack readiness gate tests (PR 24 §7)."""
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
from src.api.deps import get_db_dep
from src.api.main import app
from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearnedDetectionPointProposal
from src.db.qc_sample_learning_models import (
    PseudoDefectRule,
    QCConfirmedVisualRule,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
)
from src.db.qc_source_models import QCSourceDocument
from src.qc_model.readiness.evaluator import evaluate_readiness
from src.qc_model.readiness.gate import gate_transition


def _uid() -> str:
    return uuid.uuid4().hex


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


TP = "packR"
TENANT = "default"


def _authoring_proposal(db, **kw):
    """Create an authored proposal linked to TP via a RuleAuthoringJob."""
    job = RuleAuthoringJob(id=_uid(), tenant_id=TENANT, training_pack_id=TP, status="completed")
    db.add(job)
    db.flush()
    defaults = dict(
        id=_uid(), tenant_id=TENANT, rule_authoring_job_id=job.id, learning_job_id=None,
        proposed_code="dp", proposed_checkpoint_category="visual_defect", proposed_ai_role="primary_visual_judge",
        severity="major", status="approved", decision_rule="rule",
    )
    defaults.update(kw)
    p = QCLearnedDetectionPointProposal(**defaults)
    db.add(p)
    db.commit()
    return p


def _reviewed_source(db, status="reviewed"):
    doc = QCSourceDocument(id=_uid(), tenant_id=TENANT, training_pack_id=TP, source_type="process_spec", status=status)
    db.add(doc)
    db.commit()
    return doc


def _sample_group(db, sample_type, completed=True):
    g = SampleGroup(id=_uid(), tenant_id=TENANT, training_pack_id=TP, detection_point_id=_uid(),
                    detection_point_code="dp", sample_type=sample_type, samples_json=[])
    db.add(g)
    db.flush()
    if completed:
        db.add(SampleLearningJob(id=_uid(), tenant_id=TENANT, training_pack_id=TP, sample_group_id=g.id, status="completed"))
    db.commit()
    return g


def _approved_memory(db, code="dp", provider="qwen3.5-vl-8b-int4", status="approved", feature_type="defect_feature"):
    """Approved/applied VisualRuleMemory backed by a production-eligible provider."""
    job = SampleLearningJob(
        id=_uid(), tenant_id=TENANT, training_pack_id=TP, sample_group_id=_uid(),
        status="completed", provider=provider, model="qwen3.5-vl-8b-int4",
    )
    db.add(job)
    db.flush()
    m = VisualRuleMemory(
        id=_uid(), tenant_id=TENANT, sample_learning_job_id=job.id, training_pack_id=TP,
        detection_point_code=code, feature_type=feature_type, status=status,
    )
    db.add(m)
    db.commit()
    return m


def _fully_ready(db):
    """Set up a pack that passes all exam_ready + L2 production_assisted checks."""
    _reviewed_source(db)
    _authoring_proposal(db, proposed_checkpoint_category="visual_defect", status="approved")
    _sample_group(db, "positive")
    _sample_group(db, "defect")
    _approved_memory(db)  # approved visual memory + production-eligible provider


def _by_id(result):
    return {c.id: c for c in result.checks}


# ── Individual checks ─────────────────────────────────────────────────────


def test_incomplete_source_review_blocks_exam_ready(db):
    _fully_ready(db)
    _reviewed_source(db, status="draft")  # one unreviewed source
    result = evaluate_readiness(db, TP, TENANT)
    assert result.exam_ready_allowed is False
    assert _by_id(result)["source_documents_reviewed"].passed is False


def test_pending_proposal_blocks_exam_ready(db):
    _fully_ready(db)
    _authoring_proposal(db, status="proposed")
    result = evaluate_readiness(db, TP, TENANT)
    assert _by_id(result)["detection_points_confirmed"].passed is False
    assert result.exam_ready_allowed is False


def test_physical_measurement_unconfirmed_blocks(db):
    _reviewed_source(db)
    _sample_group(db, "positive"); _sample_group(db, "defect")
    # physical measurement proposal not approved / no decision rule.
    _authoring_proposal(db, proposed_checkpoint_category="physical_measurement",
                        proposed_ai_role="record_only", status="proposed", decision_rule="")
    result = evaluate_readiness(db, TP, TENANT)
    assert _by_id(result)["physical_measurement_boundaries_confirmed"].passed is False
    assert result.exam_ready_allowed is False


def test_physical_measurement_confirmed_passes(db):
    _reviewed_source(db)
    _sample_group(db, "positive"); _sample_group(db, "defect")
    _authoring_proposal(db, proposed_checkpoint_category="physical_measurement",
                        proposed_ai_role="record_only", status="approved", decision_rule="measure with gauge")
    result = evaluate_readiness(db, TP, TENANT)
    assert _by_id(result)["physical_measurement_boundaries_confirmed"].passed is True


def test_pending_visual_rule_memory_blocks(db):
    _fully_ready(db)
    db.add(VisualRuleMemory(id=_uid(), tenant_id=TENANT, sample_learning_job_id=_uid(),
                            training_pack_id=TP, feature_type="defect_feature", status="proposed"))
    db.commit()
    result = evaluate_readiness(db, TP, TENANT)
    assert _by_id(result)["visual_rules_approved"].passed is False
    assert result.exam_ready_allowed is False


def test_insufficient_coverage_blocks_production_assisted(db):
    _reviewed_source(db)
    _authoring_proposal(db, status="approved")
    _approved_memory(db)             # visual memory present → exam_ready ok
    _sample_group(db, "positive")    # no defect/boundary group
    result = evaluate_readiness(db, TP, TENANT)
    assert result.exam_ready_allowed is True
    assert result.on_trial_allowed is True
    assert result.production_assisted_allowed is False  # coverage insufficient
    assert result.controlled_active_allowed is False
    assert _by_id(result)["sample_coverage_sufficient"].passed is False


def test_high_risk_pseudo_defect_blocks(db):
    _fully_ready(db)
    mem_id = _uid()
    db.add(VisualRuleMemory(id=mem_id, tenant_id=TENANT, sample_learning_job_id=_uid(),
                            training_pack_id=TP, feature_type="pseudo_defect", status="approved"))
    db.add(PseudoDefectRule(id=_uid(), tenant_id=TENANT, training_pack_id=TP, visual_rule_memory_id=mem_id,
                            pattern_text="glare mistaken for crack", risk_level="high", status="proposed"))
    db.commit()
    result = evaluate_readiness(db, TP, TENANT)
    assert _by_id(result)["no_pending_high_risk_pseudo_defects"].passed is False
    assert result.exam_ready_allowed is False


def test_pending_critical_defect_blocks(db):
    _fully_ready(db)
    _authoring_proposal(db, severity="critical", status="proposed", proposed_checkpoint_category="visual_defect")
    result = evaluate_readiness(db, TP, TENANT)
    assert _by_id(result)["no_pending_critical_defect_rules"].passed is False


def test_unreviewed_conflict_blocks(db):
    _fully_ready(db)
    # An approved memory whose key already has a confirmed rule with different content.
    db.add(QCConfirmedVisualRule(id=_uid(), tenant_id=TENANT, training_pack_id=TP,
                                 detection_point_code="dp", feature_type="defect_feature",
                                 content_json={"defect_visual_features": ["old"]}, source_memory_id="other"))
    db.add(VisualRuleMemory(id=_uid(), tenant_id=TENANT, sample_learning_job_id=_uid(),
                            training_pack_id=TP, detection_point_code="dp", feature_type="defect_feature",
                            status="approved", defect_visual_features_json=["new different"]))
    db.commit()
    result = evaluate_readiness(db, TP, TENANT)
    assert _by_id(result)["no_unreviewed_conflicts"].passed is False


def test_fully_ready_pack_is_exam_ready_and_production_assisted(db):
    _fully_ready(db)
    result = evaluate_readiness(db, TP, TENANT)
    assert result.exam_ready_allowed is True
    assert result.production_assisted_allowed is True
    # L3 controlled active still requires a qualification report (later PR).
    assert result.controlled_active_allowed is False


# ── Unresolved questions + waivers ────────────────────────────────────────


def test_unresolved_question_blocks_and_waiver_unblocks(db):
    _fully_ready(db)
    p = _authoring_proposal(db, status="approved", uncertainties_json=["required view unclear"])
    result = evaluate_readiness(db, TP, TENANT)
    q_check = _by_id(result)["no_unresolved_questions"]
    assert q_check.passed is False
    assert q_check.waivable is True
    item_key = q_check.blocking_items[0]["item_key"]

    from src.qc_model.readiness.waiver import create_waiver
    create_waiver(db, TP, item_key=item_key, reason="acceptable for pilot", supervisor_id="sup1")
    result2 = evaluate_readiness(db, TP, TENANT)
    assert _by_id(result2)["no_unresolved_questions"].passed is True
    assert result2.exam_ready_allowed is True


def test_waiver_without_supervisor_rejected(client):
    resp = client.post(f"/api/qc/training-packs/{TP}/readiness-waivers",
                       json={"item_key": "x::0", "reason": "because", "supervisor_id": ""})
    assert resp.status_code == 400


def test_waiver_without_justification_rejected(client):
    resp = client.post(f"/api/qc/training-packs/{TP}/readiness-waivers",
                       json={"item_key": "x::0", "reason": "", "supervisor_id": "sup1"})
    assert resp.status_code == 400


def test_blanket_waiver_rejected(client):
    resp = client.post(f"/api/qc/training-packs/{TP}/readiness-waivers",
                       json={"item_key": "", "reason": "all good", "supervisor_id": "sup1"})
    assert resp.status_code == 400


def test_waiver_is_scoped_per_item(db):
    _fully_ready(db)
    p = _authoring_proposal(db, status="approved", uncertainties_json=["q one", "q two"])
    result = evaluate_readiness(db, TP, TENANT)
    items = _by_id(result)["no_unresolved_questions"].blocking_items
    assert len(items) == 2
    from src.qc_model.readiness.waiver import create_waiver
    create_waiver(db, TP, item_key=items[0]["item_key"], reason="ok", supervisor_id="sup1")
    result2 = evaluate_readiness(db, TP, TENANT)
    # Waiving one question does not waive the other.
    remaining = _by_id(result2)["no_unresolved_questions"].blocking_items
    assert len(remaining) == 1
    assert remaining[0]["item_key"] == items[1]["item_key"]


def test_nonwaivable_checks_cannot_be_bypassed_via_waiver(db, client):
    # Create a pack blocked by a non-waivable check (pending detection point).
    _reviewed_source(db)
    _sample_group(db, "positive"); _sample_group(db, "defect")
    _authoring_proposal(db, status="proposed")  # blocks detection_points_confirmed
    # Attempt to waive that non-waivable check explicitly.
    from src.qc_model.readiness.waiver import create_waiver, WaiverValidationError
    with pytest.raises(WaiverValidationError):
        create_waiver(db, TP, item_key="p::0", reason="skip", supervisor_id="sup1",
                      check_id="detection_points_confirmed")
    # Even a valid question-waiver does not unblock the non-waivable check.
    result = evaluate_readiness(db, TP, TENANT)
    assert result.exam_ready_allowed is False
    assert _by_id(result)["detection_points_confirmed"].passed is False


# ── Detail endpoint + transition gate ─────────────────────────────────────


def test_readiness_detail_endpoint_reports_failed_checks(client, db):
    _reviewed_source(db, status="draft")
    data = client.get(f"/api/qc/training-packs/{TP}/readiness").json()
    assert data["exam_ready_allowed"] is False
    src_check = next(c for c in data["checks"] if c["id"] == "source_documents_reviewed")
    assert src_check["passed"] is False
    assert src_check["blocking_items"]


def test_transition_gate_blocks_exam_ready_when_incomplete(db):
    _reviewed_source(db, status="draft")
    decision = gate_transition(db, TP, "exam_ready", TENANT)
    assert decision.allowed is False


def test_transition_gate_production_assisted_needs_coverage(db):
    _reviewed_source(db)
    _authoring_proposal(db, status="approved")
    _approved_memory(db)
    _sample_group(db, "positive")  # no defect/boundary
    assert gate_transition(db, TP, "on_trial", TENANT).allowed is True
    pa = gate_transition(db, TP, "production_assisted", TENANT)
    assert pa.allowed is False
    assert pa.reason == "production_prerequisites_incomplete"


def test_transition_gate_controlled_active_requires_qualification(db):
    _fully_ready(db)
    # Fully L2-ready, but L3 controlled_active still fails on qualification.
    assert gate_transition(db, TP, "production_assisted", TENANT).allowed is True
    active = gate_transition(db, TP, "active", TENANT)
    assert active.allowed is False
    assert active.reason == "qualification_required_for_controlled_active"


def test_ui_readiness_panel_smoke(client, db):
    _reviewed_source(db, status="draft")
    page = client.get(f"/admin/qc-model/training-packs/{TP}/readiness")
    assert page.status_code == 200
    assert "Training Pack Readiness Gate" in page.text
    assert "Readiness checklist" in page.text


# ── Fail closed for unknown / cross-tenant packs ──────────────────────────


def test_unknown_pack_fails_closed(db):
    # A pack id with no rows at all must not be exam-ready via vacuous passes.
    result = evaluate_readiness(db, "never-seen-pack", TENANT)
    assert result.pack_known is False
    assert result.exam_ready_allowed is False
    assert result.on_trial_allowed is False
    assert result.active_allowed is False


def test_cross_tenant_pack_fails_closed(db):
    # Fully-ready pack owned by TENANT ("default").
    _fully_ready(db)
    owner = evaluate_readiness(db, TP, TENANT)
    assert owner.exam_ready_allowed is True
    # A different tenant asking about the same pack sees only empty queries.
    other = evaluate_readiness(db, TP, "tenant_intruder")
    assert other.pack_known is False
    assert other.exam_ready_allowed is False
    assert other.active_allowed is False


def test_gate_rejects_cross_tenant_pack(db):
    _fully_ready(db)
    decision = gate_transition(db, TP, "exam_ready", "tenant_intruder")
    assert decision.allowed is False
    assert decision.reason == "unknown_or_cross_tenant_pack"


# ── Supervisor source review action (unblocks the source check) ───────────


def test_source_review_action_unblocks_source_check(db):
    from src.qc_model.ingestion import service
    # A draft source blocks exam_ready and there is now a supported way to clear it.
    doc = _reviewed_source(db, status="draft")
    _authoring_proposal(db, status="approved")
    _approved_memory(db)
    _sample_group(db, "positive"); _sample_group(db, "defect")
    assert evaluate_readiness(db, TP, TENANT).exam_ready_allowed is False

    service.review_source_document(db, doc.id, decision="reviewed", tenant_id=TENANT, reviewer="sup1")
    assert evaluate_readiness(db, TP, TENANT).exam_ready_allowed is True


def test_source_review_endpoint(client, db):
    doc = _reviewed_source(db, status="draft")
    resp = client.post(f"/api/qc/sources/{doc.id}/review",
                       json={"decision": "reviewed", "tenant_id": TENANT, "reviewer": "sup1"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "reviewed"


def test_source_review_rejects_bad_decision(client, db):
    doc = _reviewed_source(db, status="draft")
    resp = client.post(f"/api/qc/sources/{doc.id}/review",
                       json={"decision": "active", "tenant_id": TENANT})
    assert resp.status_code == 422


def test_source_review_is_tenant_scoped(client, db):
    doc = _reviewed_source(db, status="draft")
    resp = client.post(f"/api/qc/sources/{doc.id}/review",
                       json={"decision": "reviewed", "tenant_id": "other"})
    assert resp.status_code == 404


# ── UI waiver preserves tenant_id ─────────────────────────────────────────


def test_ui_waiver_preserves_tenant(client, db):
    from src.qc_model.readiness.waiver import list_waivers
    resp = client.post(
        f"/admin/qc-model/training-packs/{TP}/readiness-waivers",
        data={"item_key": "p::0", "reason": "ok for pilot", "supervisor_id": "sup1", "tenant_id": "t1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "tenant_id=t1" in resp.headers["location"]
    # Waiver written under t1, not default.
    assert len(list_waivers(db, TP, "t1")) == 1
    assert len(list_waivers(db, TP, "default")) == 0
