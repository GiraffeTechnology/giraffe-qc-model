"""Production Readiness PR24-fix regression tests (§4.1, 4.3–4.8)."""
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
    CaptureArtifactRule,
    PseudoDefectRule,
    QCConfirmedVisualRule,
    SampleGroup,
    SampleLearningJob,
    VisualRuleMemory,
)
from src.db.qc_source_models import QCSourceDocument
from src.qc_model.readiness.evaluator import evaluate_readiness
from src.qc_model.training_pack.ownership import (
    CrossTenantTrainingPack,
    assert_pack_accessible,
    pack_known_for_tenant,
)


TP = "packP"
T1 = "tenant_1"
T2 = "tenant_2"


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


# ── Helpers ────────────────────────────────────────────────────────────────


def _source(db, tenant=T1, status="reviewed"):
    d = QCSourceDocument(id=_uid(), tenant_id=tenant, training_pack_id=TP, source_type="process_spec", status=status)
    db.add(d)
    db.commit()
    return d


def _proposal(db, tenant=T1, code="dp", category="visual_defect", role="primary_visual_judge", status="approved"):
    job = RuleAuthoringJob(id=_uid(), tenant_id=tenant, training_pack_id=TP, status="completed")
    db.add(job)
    db.flush()
    p = QCLearnedDetectionPointProposal(
        id=_uid(), tenant_id=tenant, rule_authoring_job_id=job.id, learning_job_id=None,
        proposed_code=code, proposed_checkpoint_category=category, proposed_ai_role=role,
        severity="major", status=status, decision_rule="rule",
    )
    db.add(p)
    db.commit()
    return p


def _group(db, sample_type, tenant=T1, completed=True):
    g = SampleGroup(id=_uid(), tenant_id=tenant, training_pack_id=TP, detection_point_id=_uid(),
                    detection_point_code="dp", sample_type=sample_type, samples_json=[])
    db.add(g)
    db.flush()
    if completed:
        db.add(SampleLearningJob(id=_uid(), tenant_id=tenant, training_pack_id=TP,
                                 sample_group_id=g.id, status="completed"))
    db.commit()
    return g


def _memory(db, tenant=T1, code="dp", provider="qwen3.5-vl-8b-int4", status="approved", feature="defect_feature"):
    job = SampleLearningJob(id=_uid(), tenant_id=tenant, training_pack_id=TP, sample_group_id=_uid(),
                            status="completed", provider=provider, model="m")
    db.add(job)
    db.flush()
    m = VisualRuleMemory(id=_uid(), tenant_id=tenant, sample_learning_job_id=job.id, training_pack_id=TP,
                         detection_point_code=code, feature_type=feature, status=status)
    db.add(m)
    db.commit()
    return m


def _l2_ready(db):
    _source(db)
    _proposal(db)
    _group(db, "positive")
    _group(db, "defect")
    _memory(db)


# ── §4.1 VisualRuleMemory mandatory ────────────────────────────────────────


def test_no_visual_memory_blocks_all_production_modes(db):
    # Reviewed source + approved proposal + sample groups + completed jobs,
    # BUT no approved/applied VisualRuleMemory.
    _source(db)
    _proposal(db)
    _group(db, "positive")
    _group(db, "defect")
    r = evaluate_readiness(db, TP, T1)
    assert r.exam_ready_allowed is False
    assert r.production_assisted_allowed is False
    assert r.controlled_active_allowed is False
    assert "visual_rule_memory_required" in r.to_dict()["blocking_checks"]


def test_confirmed_visual_rule_satisfies_memory_requirement(db):
    _source(db)
    _proposal(db)
    _group(db, "positive")
    _group(db, "defect")
    # A confirmed visual rule (not just memory) also satisfies §4.1.
    db.add(QCConfirmedVisualRule(id=_uid(), tenant_id=T1, training_pack_id=TP,
                                 detection_point_code="dp", feature_type="defect_feature",
                                 content_json={}, source_memory_id=_uid()))
    db.commit()
    r = evaluate_readiness(db, TP, T1)
    assert r.exam_ready_allowed is True


def test_pending_memory_blocks_exam_ready(db):
    _source(db)
    _proposal(db)
    _group(db, "positive")
    _group(db, "defect")
    _memory(db, status="proposed")  # not approved/applied
    r = evaluate_readiness(db, TP, T1)
    assert r.exam_ready_allowed is False


# ── §4.3 Mock provider does not satisfy production ─────────────────────────


def test_mock_provider_blocks_production_but_not_exam_ready(db):
    _source(db)
    _proposal(db)
    _group(db, "positive")
    _group(db, "defect")
    _memory(db, provider="mock_sample_learning")
    r = evaluate_readiness(db, TP, T1)
    assert r.exam_ready_allowed is True  # knowledge complete
    assert r.production_assisted_allowed is False
    assert "production_eligible_provider" in r.to_dict()["blocking_checks"]


@pytest.mark.parametrize("provider", ["mock_x", "fake_vlm", "vlm_stub", "qwen_skeleton", None])
def test_non_production_providers_rejected(db, provider):
    _source(db)
    _proposal(db)
    _group(db, "positive")
    _group(db, "defect")
    _memory(db, provider=provider)
    r = evaluate_readiness(db, TP, T1)
    assert r.production_assisted_allowed is False


# ── §4.4 Unified ownership resolver ────────────────────────────────────────


def test_pack_known_only_via_sample_group_is_cross_tenant_protected(db):
    _group(db, "positive", tenant=T1)
    assert pack_known_for_tenant(db, TP, T1) is True
    assert pack_known_for_tenant(db, TP, T2) is False
    with pytest.raises(CrossTenantTrainingPack):
        assert_pack_accessible(db, TP, T2)


def test_pack_known_only_via_visual_memory_is_cross_tenant_protected(db):
    _memory(db, tenant=T1)
    assert pack_known_for_tenant(db, TP, T2) is False
    with pytest.raises(CrossTenantTrainingPack):
        assert_pack_accessible(db, TP, T2)


def test_pack_known_only_via_confirmed_rule_is_cross_tenant_protected(db):
    db.add(QCConfirmedVisualRule(id=_uid(), tenant_id=T1, training_pack_id=TP,
                                 detection_point_code="dp", feature_type="defect_feature",
                                 content_json={}, source_memory_id=_uid()))
    db.commit()
    assert pack_known_for_tenant(db, TP, T2) is False
    with pytest.raises(CrossTenantTrainingPack):
        assert_pack_accessible(db, TP, T2)


def test_cross_tenant_readiness_fails_closed(db):
    _l2_ready(db)  # owned by T1
    other = evaluate_readiness(db, TP, T2)
    assert other.pack_known is False
    assert other.exam_ready_allowed is False
    assert other.production_assisted_allowed is False


def test_cross_tenant_source_create_returns_404(client, db):
    _group(db, "positive", tenant=T1)  # binds TP to T1
    resp = client.post(
        f"/api/qc/training-packs/{TP}/sources",
        json={"source_type": "process_spec", "tenant_id": T2, "text_content": "x"},
    )
    assert resp.status_code == 404


# ── §4.7 Pseudo-defect / capture-artifact closure ──────────────────────────


def test_pending_pseudo_defect_blocks_production(db):
    _l2_ready(db)
    m = db.query(VisualRuleMemory).filter_by(training_pack_id=TP).first()
    db.add(PseudoDefectRule(id=_uid(), tenant_id=T1, training_pack_id=TP, visual_rule_memory_id=m.id,
                            pattern_text="glare", risk_level="normal", status="proposed"))
    db.commit()
    r = evaluate_readiness(db, TP, T1)
    assert r.exam_ready_allowed is True
    assert r.production_assisted_allowed is False
    assert "pseudo_defect_rules_closed" in r.to_dict()["blocking_checks"]


def test_pending_capture_artifact_blocks_production(db):
    _l2_ready(db)
    m = db.query(VisualRuleMemory).filter_by(training_pack_id=TP).first()
    db.add(CaptureArtifactRule(id=_uid(), tenant_id=T1, training_pack_id=TP, visual_rule_memory_id=m.id,
                               pattern_text="reflection", status="proposed"))
    db.commit()
    r = evaluate_readiness(db, TP, T1)
    assert r.production_assisted_allowed is False
    assert "capture_artifact_rules_closed" in r.to_dict()["blocking_checks"]


def test_approving_memory_closes_associated_rules(db):
    from src.qc_model.sample_learning import service
    m = _memory(db, status="proposed")
    db.add(PseudoDefectRule(id=_uid(), tenant_id=T1, training_pack_id=TP, visual_rule_memory_id=m.id,
                            pattern_text="glare", status="proposed"))
    db.add(CaptureArtifactRule(id=_uid(), tenant_id=T1, training_pack_id=TP, visual_rule_memory_id=m.id,
                               pattern_text="blur", status="proposed"))
    db.commit()
    service.review_memory(db, m.id, "approve", "sup1", tenant_id=T1)
    assert db.query(PseudoDefectRule).filter_by(visual_rule_memory_id=m.id).first().status == "approved"
    assert db.query(CaptureArtifactRule).filter_by(visual_rule_memory_id=m.id).first().status == "approved"


def test_applying_memory_marks_rules_applied(db):
    from src.qc_model.sample_learning import service
    m = _memory(db, status="approved")
    db.add(PseudoDefectRule(id=_uid(), tenant_id=T1, training_pack_id=TP, visual_rule_memory_id=m.id,
                            pattern_text="glare", status="proposed"))
    db.commit()
    service.apply_approved_memory(db, TP, m.id, "sup1", tenant_id=T1)
    assert db.query(PseudoDefectRule).filter_by(visual_rule_memory_id=m.id).first().status == "applied"


# ── §4.8 target_mode-aware endpoint ────────────────────────────────────────


def test_readiness_endpoint_accepts_target_mode(client, db):
    _l2_ready(db)
    data = client.get(f"/api/qc/training-packs/{TP}/readiness?tenant_id={T1}&target_mode=production_assisted").json()
    assert data["target_mode"] == "production_assisted"
    for key in ("exam_ready_allowed", "production_assisted_allowed", "controlled_active_allowed",
                "blocking_checks", "checks"):
        assert key in data
    assert data["production_assisted_allowed"] is True
    assert data["controlled_active_allowed"] is False


def test_controlled_active_mode_lists_qualification_blocker(client, db):
    _l2_ready(db)
    data = client.get(f"/api/qc/training-packs/{TP}/readiness?tenant_id={T1}&target_mode=controlled_active").json()
    assert data["controlled_active_allowed"] is False
    assert "controlled_active_qualification" in data["blocking_checks"]


# ── §4.5 UI tenant preservation ────────────────────────────────────────────


def test_ui_create_source_writes_under_tenant(client, db):
    _group(db, "positive", tenant=T1)  # bind TP to T1
    resp = client.post(
        f"/admin/qc-model/training-packs/{TP}/sources",
        data={"source_type": "process_spec", "text_content": "spec", "tenant_id": T1},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert f"tenant_id={T1}" in resp.headers["location"]
    # Written under T1, not default.
    assert db.query(QCSourceDocument).filter_by(training_pack_id=TP, tenant_id=T1).count() == 1
    assert db.query(QCSourceDocument).filter_by(training_pack_id=TP, tenant_id="default").count() == 0


def test_ui_default_tenant_backward_compatible(client, db):
    resp = client.post(
        f"/admin/qc-model/training-packs/{TP}/sources",
        data={"source_type": "process_spec", "text_content": "spec"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # No tenant query for default (backward compatible).
    assert "tenant_id=" not in resp.headers["location"]
    assert db.query(QCSourceDocument).filter_by(training_pack_id=TP, tenant_id="default").count() == 1


# ── §4.6 UI waiver errors visible ──────────────────────────────────────────


def test_ui_waiver_missing_supervisor_shows_error(client, db):
    # Whitespace-only supervisor reaches the handler (empty is rejected earlier)
    # and produces a visible error instead of a silent redirect.
    resp = client.post(
        f"/admin/qc-model/training-packs/{TP}/readiness-waivers",
        data={"item_key": "x::0", "reason": "ok", "supervisor_id": "   "},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "waiver_error" in resp.headers["location"]


def test_ui_waiver_missing_justification_shows_error(client, db):
    resp = client.post(
        f"/admin/qc-model/training-packs/{TP}/readiness-waivers",
        data={"item_key": "x::0", "reason": "   ", "supervisor_id": "sup1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "waiver_error" in resp.headers["location"]


def test_ui_waiver_blanket_item_shows_error(client, db):
    # A blanket (whitespace) item_key is rejected and surfaced visibly.
    resp = client.post(
        f"/admin/qc-model/training-packs/{TP}/readiness-waivers",
        data={"item_key": "   ", "reason": "ok", "supervisor_id": "sup1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "waiver_error" in resp.headers["location"]


def test_ui_waiver_error_rendered_in_panel(client, db):
    _source(db, status="draft")  # make the pack known
    page = client.get(
        f"/admin/qc-model/training-packs/{TP}/readiness?tenant_id={T1}&waiver_error=missing+justification"
    )
    assert page.status_code == 200
    assert "Waiver rejected" in page.text
