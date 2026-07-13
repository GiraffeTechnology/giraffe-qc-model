"""Production deployment hardening tests (PR 29)."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_readiness_models  # noqa: F401
import src.db.qc_production_models  # noqa: F401
import src.db.qc_qualification_models  # noqa: F401
import src.db.qc_incident_models  # noqa: F401
from src.api.deps import get_db_dep
from src.api.main import app
from src.qc_model import observability
from src.qc_model.readiness.evaluator import evaluate_readiness

REPO_ROOT = Path(__file__).resolve().parent.parent


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


# ── APP_ENV=production disables mock/fake providers ──────────────────────────


def test_production_env_disables_mock_inspection_provider(monkeypatch):
    from src.qc_model.production.provider import get_production_inspection_provider, ProductionProviderNotConfigured
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "mock")
    with pytest.raises(ProductionProviderNotConfigured):
        get_production_inspection_provider()


def test_production_env_disables_mock_sample_learning(monkeypatch):
    from src.qc_model.sample_learning.provider import sample_learning_mock_allowed, get_sample_learning_provider
    from src.qc_model.sample_learning.provider import Qwen35VLSampleLearningProvider
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("QC_SAMPLE_LEARNING_ALLOW_MOCK", raising=False)
    assert sample_learning_mock_allowed() is False
    assert isinstance(get_sample_learning_provider(), Qwen35VLSampleLearningProvider)


def test_production_env_disables_fake_provider(monkeypatch):
    from src.config import fake_provider_allowed
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("QC_ALLOW_TEST_ADAPTER", raising=False)
    assert fake_provider_allowed() is False


# ── Review finding 1: overrides cannot re-enable mock/fake in production ──────


def test_production_ignores_mock_sample_learning_override(monkeypatch):
    from src.qc_model.sample_learning.provider import (
        sample_learning_mock_allowed, get_sample_learning_provider, Qwen35VLSampleLearningProvider,
    )
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("QC_SAMPLE_LEARNING_ALLOW_MOCK", "true")  # must be ignored in prod
    assert sample_learning_mock_allowed() is False
    assert isinstance(get_sample_learning_provider(), Qwen35VLSampleLearningProvider)


def test_production_ignores_fake_adapter_override(monkeypatch):
    from src.config import fake_provider_allowed
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("QC_ALLOW_TEST_ADAPTER", "true")  # must be ignored in prod
    assert fake_provider_allowed() is False


def test_overrides_still_work_outside_production(monkeypatch):
    from src.qc_model.sample_learning.provider import sample_learning_mock_allowed
    from src.config import fake_provider_allowed
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("QC_SAMPLE_LEARNING_ALLOW_MOCK", "true")
    monkeypatch.setenv("QC_ALLOW_TEST_ADAPTER", "true")
    assert sample_learning_mock_allowed() is True
    assert fake_provider_allowed() is True


def test_server_provider_unconfigured_fails_closed(monkeypatch):
    from src.qc_model.production.provider import get_production_inspection_provider, ServerVLMInspectionProvider
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "server_vlm")
    monkeypatch.delenv("QC_SERVER_VLM_BASE_URL", raising=False)
    provider = get_production_inspection_provider()
    assert isinstance(provider, ServerVLMInspectionProvider)
    assert provider.is_configured is False  # production APIs fail closed on use


# ── Provider-eligibility endpoint ────────────────────────────────────────────


def test_provider_eligibility_endpoint(client, monkeypatch):
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "server_vlm")
    monkeypatch.setenv("QC_SERVER_VLM_BASE_URL", "https://vlm.internal")
    data = client.get("/api/qc/production/provider-eligibility").json()
    assert data["selected"] == "server_vlm"
    assert data["configured"] is True
    assert data["production_eligible"] is True
    assert data["model"] == "qwen3.5-vl-8b-int4"


def test_provider_eligibility_mock_not_eligible(client, monkeypatch):
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "mock")
    data = client.get("/api/qc/production/provider-eligibility").json()
    assert data["production_eligible"] is False


# ── Observability ────────────────────────────────────────────────────────────


def test_readiness_emits_observability_event(db):
    observability.reset()
    evaluate_readiness(db, "some-pack", "default", target_mode="controlled_active")
    snap = observability.snapshot()
    assert snap["counters"].get(observability.EV_READINESS_GATE_RESULT, 0) >= 1


def test_metrics_endpoint(client):
    observability.reset()
    evaluate_readiness  # ensure import
    client.get("/api/qc/training-packs/p/readiness?target_mode=controlled_active")
    data = client.get("/api/qc/production/metrics").json()
    assert "counters" in data and "latency" in data
    assert data["counters"].get(observability.EV_READINESS_GATE_RESULT, 0) >= 1


def test_record_never_raises():
    # Even with un-serializable fields, observability must not raise.
    observability.record("readiness_gate_result", tenant_id="t", weird=object())


# ── Review finding 3: latency uses bounded/running aggregate, not a list ─────


def test_latency_metrics_are_bounded_aggregate():
    observability.reset()
    for i in range(5000):
        observability.observe_latency("server_vlm_inspect", float(i % 100))
    # Internal storage is a fixed-size running aggregate, never a growing list.
    agg = observability._latency_ms["server_vlm_inspect"]
    assert isinstance(agg, dict)
    assert set(agg) == {"count", "sum_ms", "min_ms", "max_ms"}
    snap = observability.snapshot()["latency"]["server_vlm_inspect"]
    assert snap["count"] == 5000
    assert snap["min_ms"] == 0.0
    assert snap["max_ms"] == 99.0


# ── Production-flow helpers (schema-error + human-override findings) ──────────


def _l2_ready(db, tenant="t1", confirmed_content=None):
    import uuid as _uuid
    from src.db.qc_source_models import QCSourceDocument
    from src.db.qc_authoring_models import RuleAuthoringJob
    from src.db.qc_learning_models import QCLearnedDetectionPointProposal
    from src.db.qc_sample_learning_models import (
        QCConfirmedVisualRule, SampleGroup, SampleLearningJob, VisualRuleMemory,
    )

    uid = lambda: _uuid.uuid4().hex  # noqa: E731
    tp = "packDH"
    db.add(QCSourceDocument(id=uid(), tenant_id=tenant, training_pack_id=tp, source_type="process_spec", status="reviewed"))
    job = RuleAuthoringJob(id=uid(), tenant_id=tenant, training_pack_id=tp, status="completed")
    db.add(job); db.flush()
    db.add(QCLearnedDetectionPointProposal(
        id=uid(), tenant_id=tenant, rule_authoring_job_id=job.id, learning_job_id=None,
        proposed_code="dp", proposed_checkpoint_category="visual_defect",
        proposed_ai_role="primary_visual_judge", severity="major", status="approved", decision_rule="r"))
    mjob = SampleLearningJob(id=uid(), tenant_id=tenant, training_pack_id=tp, sample_group_id=uid(),
                             status="completed", provider="qwen3.5-vl-8b-int4", model="m")
    db.add(mjob); db.flush()
    db.add(VisualRuleMemory(id=uid(), tenant_id=tenant, sample_learning_job_id=mjob.id, training_pack_id=tp,
                            detection_point_code="dp", feature_type="defect_feature", status="applied"))
    db.add(QCConfirmedVisualRule(id=uid(), tenant_id=tenant, training_pack_id=tp, detection_point_code="dp",
                                 feature_type="defect_feature", content_json=confirmed_content or {}, source_memory_id=uid()))
    for st in ("positive", "defect"):
        g = SampleGroup(id=uid(), tenant_id=tenant, training_pack_id=tp, detection_point_id=uid(),
                        detection_point_code="dp", sample_type=st, samples_json=[])
        db.add(g); db.flush()
        db.add(SampleLearningJob(id=uid(), tenant_id=tenant, training_pack_id=tp, sample_group_id=g.id, status="completed"))
    db.commit()
    return tp


def _make_provider(disposition, raise_schema=False, raise_provider=False):
    from src.qc_model.production.provider import (
        DetectionInspectionRequest, DetectionInspectionResult, ProductionInspectionProvider,
        ProductionProviderSchemaError, ProductionProviderError,
    )

    class _P(ProductionInspectionProvider):
        provider_name = "server_vlm"
        model_name = "qwen3.5-vl-8b-int4"
        production_eligible = True
        is_configured = True

        def inspect(self, request: DetectionInspectionRequest) -> DetectionInspectionResult:
            if raise_schema:
                raise ProductionProviderSchemaError("server_vlm malformed output: missing fields")
            if raise_provider:
                raise ProductionProviderError("server_vlm backend error: TimeoutException")
            return DetectionInspectionResult(disposition=disposition, observed_features=["f"],
                                             evidence_regions=[{"bbox": [1, 2, 3, 4]}], confidence=0.9,
                                             provider="server_vlm", model="qwen3.5-vl-8b-int4")

    return _P()


def _session_with_capture(db, tp, tenant="t1"):
    from src.qc_model.production import service
    s = service.create_session(db, tp, tenant, operator_id="op1")
    service.add_capture(db, s.id, "s3://img.jpg", tenant, {})
    return s


# ── Review finding 2: malformed server VLM output → schema_validation_error ──


def test_malformed_output_counts_as_schema_validation_error(db):
    from src.qc_model.production import service
    tp = _l2_ready(db)
    s = _session_with_capture(db, tp)
    observability.reset()
    run = service.run_inspection(db, s.id, "t1", provider=_make_provider("pass_recommended", raise_schema=True))
    assert run.status == "failed"
    counters = observability.snapshot()["counters"]
    assert counters.get(observability.EV_SCHEMA_VALIDATION_ERROR, 0) >= 1
    assert counters.get(observability.EV_PROVIDER_ERROR, 0) == 0


def test_real_server_provider_malformed_json_is_schema_error(db):
    # End-to-end: ServerVLMInspectionProvider parses a malformed backend response
    # -> ProductionProviderSchemaError -> schema_validation_error.
    from src.qc_model.production import service
    from src.qc_model.production.provider import ServerVLMInspectionProvider

    class _BadBackend(ServerVLMInspectionProvider):
        def __init__(self):
            super().__init__(base_url="https://vlm.internal", model="qwen3.5-vl-8b-int4")

        def _call_backend(self, payload):
            return {"disposition": "pass_recommended"}  # missing required fields

    tp = _l2_ready(db)
    s = _session_with_capture(db, tp)
    observability.reset()
    run = service.run_inspection(db, s.id, "t1", provider=_BadBackend())
    assert run.status == "failed"
    counters = observability.snapshot()["counters"]
    assert counters.get(observability.EV_SCHEMA_VALIDATION_ERROR, 0) >= 1
    assert counters.get(observability.EV_PROVIDER_ERROR, 0) == 0


def test_generic_provider_error_counts_as_provider_error(db):
    from src.qc_model.production import service
    tp = _l2_ready(db)
    s = _session_with_capture(db, tp)
    observability.reset()
    run = service.run_inspection(db, s.id, "t1", provider=_make_provider("pass_recommended", raise_provider=True))
    assert run.status == "failed"
    counters = observability.snapshot()["counters"]
    assert counters.get(observability.EV_PROVIDER_ERROR, 0) >= 1
    assert counters.get(observability.EV_SCHEMA_VALIDATION_ERROR, 0) == 0


# ── Review finding 4: review-rec + human-review is not an override ───────────


def _run_and_decide(db, tp, model_disposition, human_decision):
    from src.qc_model.production import service
    s = _session_with_capture(db, tp)
    run = service.run_inspection(db, s.id, "t1", provider=_make_provider(model_disposition))
    observability.reset()
    service.record_final_decision(db, run.id, human_decision, "sup1", "t1")
    return observability.snapshot()["counters"].get(observability.EV_HUMAN_OVERRIDE, 0)


def test_review_rec_then_human_review_is_not_override(db):
    tp = _l2_ready(db)
    # Model recommends review_required; human decides review → agreement.
    assert _run_and_decide(db, tp, "review_required", "review") == 0


def test_pass_rec_then_human_pass_is_not_override(db):
    tp = _l2_ready(db)
    assert _run_and_decide(db, tp, "pass_recommended", "pass") == 0


def test_pass_rec_then_human_reject_is_override(db):
    tp = _l2_ready(db)
    assert _run_and_decide(db, tp, "pass_recommended", "reject") >= 1


def test_reject_rec_then_human_reject_is_not_override(db):
    tp = _l2_ready(db)
    assert _run_and_decide(db, tp, "reject_recommended", "reject") == 0


def test_reject_rec_then_human_pass_is_override(db):
    tp = _l2_ready(db)
    assert _run_and_decide(db, tp, "reject_recommended", "pass") >= 1


def test_review_rec_then_human_pass_is_override(db):
    tp = _l2_ready(db)
    # Supervisor clears a review to pass → override (spec §4).
    assert _run_and_decide(db, tp, "review_required", "pass") >= 1


def test_override_family_helper_direct():
    from src.qc_model.production.service import _is_human_override
    assert _is_human_override("review_required", "review") is False
    assert _is_human_override("capture_retry_required", "review") is False
    assert _is_human_override("measurement_required", "review") is False
    assert _is_human_override("pass_recommended", "pass") is False
    assert _is_human_override("reject_recommended", "reject") is False
    assert _is_human_override("pass_recommended", "reject") is True
    assert _is_human_override("reject_recommended", "pass") is True
    assert _is_human_override("review_required", "pass") is True


# ── Audit tables have no mutating public API ─────────────────────────────────


def test_audit_resources_have_no_mutating_api():
    paths = app.openapi()["paths"]
    audit_markers = ("readiness-waivers", "evidence", "final-decision", "approval",
                     "incidents", "suspensions", "shadow-observations")
    offenders = []
    for path, methods in paths.items():
        if any(m in path for m in audit_markers):
            for verb in methods:
                if verb.lower() in ("delete", "put", "patch"):
                    offenders.append(f"{verb.upper()} {path}")
    assert offenders == [], f"append-only audit resources must not expose mutating methods: {offenders}"


# ── Supervisor identity required ─────────────────────────────────────────────


def test_waiver_requires_supervisor_identity(db):
    from src.qc_model.readiness.waiver import create_waiver, WaiverValidationError
    with pytest.raises(WaiverValidationError):
        create_waiver(db, "pack", item_key="k", reason="r", supervisor_id="")


def test_incident_confirmation_requires_identity(db):
    from src.qc_model.incident import service as inc_service
    # Bind a pack so report is accepted, then confirm with a blank identity.
    from src.db.qc_source_models import QCSourceDocument
    db.add(QCSourceDocument(id=uuid.uuid4().hex, tenant_id="t1", training_pack_id="packH",
                            source_type="process_spec", status="reviewed"))
    db.commit()
    inc = inc_service.report_incident(db, "packH", "false_pass", "t1", reported_by="qc")
    with pytest.raises(inc_service.InvalidConfirmation):
        inc_service.confirm_incident(db, inc.id, "confirmed_false_pass", "  ", "t1", confirmation_reason="r")


# ── Docs links + terminology ─────────────────────────────────────────────────


@pytest.mark.parametrize("doc", [
    "docs/production-readiness.md",
    "docs/production-assisted-mode.md",
    "docs/real-vlm-provider.md",
    "docs/qualification-and-shadow-mode.md",
    "docs/false-pass-incident-response.md",
    "docs/production-deployment.md",
])
def test_required_docs_exist(doc):
    assert (REPO_ROOT / doc).exists(), f"missing doc: {doc}"


def test_production_deployment_doc_linked_from_readme():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/production-deployment.md" in readme, "README must link the deployment-hardening doc"


def test_no_desktop_pc_mnn_in_src_or_docs():
    offenders = []
    for base in ("src", "docs"):
        for p in (REPO_ROOT / base).rglob("*"):
            if p.suffix in (".py", ".md", ".html") and "desktop_pc_mnn" in p.read_text(encoding="utf-8", errors="ignore"):
                offenders.append(str(p.relative_to(REPO_ROOT)))
    assert offenders == [], f"forbidden term desktop_pc_mnn found in: {offenders}"


# ── Migration up/down/up (009 → 016) ─────────────────────────────────────────


def test_migration_up_down_up(tmp_path):
    pytest.importorskip("alembic")
    db_file = tmp_path / "mig.db"
    env = {**os.environ, "QC_DB_URL": f"sqlite:///{db_file}"}

    def alembic(*args):
        # Invoke via the current interpreter so the test does not depend on the
        # `alembic` console script being resolvable on the caller's PATH.
        return subprocess.run([sys.executable, "-m", "alembic", *args],
                              cwd=REPO_ROOT, env=env,
                              capture_output=True, text=True)

    assert alembic("upgrade", "head").returncode == 0
    assert alembic("downgrade", "base").returncode == 0
    up = alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
