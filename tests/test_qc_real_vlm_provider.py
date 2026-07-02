"""Real VLM provider integration tests (PR 26)."""
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
from src.db.qc_authoring_models import RuleAuthoringJob
from src.db.qc_learning_models import QCLearnedDetectionPointProposal
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
    ProductionProviderError,
    ProductionProviderNotConfigured,
    ServerVLMInspectionProvider,
    get_production_inspection_provider,
    parse_provider_response,
)
from src.qc_model.production.runtime import TabletRuntimeNotAllowedForProduction

TP = "packVLM"
T1 = "tenant_1"


def _uid() -> str:
    return uuid.uuid4().hex


def _good_response(dp="dp", disposition="pass_recommended", evidence=None):
    return {
        "detection_point_code": dp,
        "disposition": disposition,
        "observed_features": ["f1"],
        "defect_features": [],
        "normal_features_matched": ["f1"],
        "evidence_regions": [{"bbox": [1, 2, 3, 4]}] if evidence is None else evidence,
        "confidence": 0.91,
        "uncertainty": "",
        "review_required_conditions": [],
        "provider": "server_vlm",
        "model": "qwen3.5-vl-8b-int4",
    }


class _ConfiguredServerProvider(ServerVLMInspectionProvider):
    """A configured server VLM provider whose backend is stubbed (no live server)."""

    def __init__(self, backend_response):
        super().__init__(base_url="https://vlm.internal", model="qwen3.5-vl-8b-int4")
        self._backend_response = backend_response

    def _call_backend(self, payload):
        if isinstance(self._backend_response, Exception):
            raise self._backend_response
        return self._backend_response


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    yield s
    s.close()


def _l2_ready(db, confirmed_content=None):
    db.add(QCSourceDocument(id=_uid(), tenant_id=T1, training_pack_id=TP, source_type="process_spec", status="reviewed"))
    job = RuleAuthoringJob(id=_uid(), tenant_id=T1, training_pack_id=TP, status="completed")
    db.add(job)
    db.flush()
    db.add(QCLearnedDetectionPointProposal(
        id=_uid(), tenant_id=T1, rule_authoring_job_id=job.id, learning_job_id=None,
        proposed_code="dp", proposed_checkpoint_category="visual_defect",
        proposed_ai_role="primary_visual_judge", severity="major", status="approved", decision_rule="r",
    ))
    mjob = SampleLearningJob(id=_uid(), tenant_id=T1, training_pack_id=TP, sample_group_id=_uid(),
                             status="completed", provider="qwen3.5-vl-8b-int4", model="m")
    db.add(mjob)
    db.flush()
    db.add(VisualRuleMemory(id=_uid(), tenant_id=T1, sample_learning_job_id=mjob.id, training_pack_id=TP,
                            detection_point_code="dp", feature_type="defect_feature", status="applied"))
    for st in ("positive", "defect"):
        g = SampleGroup(id=_uid(), tenant_id=T1, training_pack_id=TP, detection_point_id=_uid(),
                        detection_point_code="dp", sample_type=st, samples_json=[])
        db.add(g)
        db.flush()
        db.add(SampleLearningJob(id=_uid(), tenant_id=T1, training_pack_id=TP, sample_group_id=g.id, status="completed"))
    db.add(QCConfirmedVisualRule(id=_uid(), tenant_id=T1, training_pack_id=TP, detection_point_code="dp",
                                 feature_type="defect_feature", content_json=confirmed_content or {}, source_memory_id=_uid()))
    db.commit()


def _session_with_capture(db):
    s = service.create_session(db, TP, T1, operator_id="op1")
    service.add_capture(db, s.id, "s3://img.jpg", T1, {"lighting": "ok"})
    return s


# ── Provider not configured fails closed ─────────────────────────────────────


def test_unconfigured_server_provider_fails_closed(db):
    _l2_ready(db)
    s = _session_with_capture(db)
    provider = ServerVLMInspectionProvider(base_url="")  # not configured
    with pytest.raises(ProductionProviderNotConfigured):
        service.run_inspection(db, s.id, T1, provider=provider)


def test_selecting_server_provider_without_config_fails_closed(db, monkeypatch):
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "server_vlm")
    monkeypatch.delenv("QC_SERVER_VLM_BASE_URL", raising=False)
    _l2_ready(db)
    s = _session_with_capture(db)
    with pytest.raises(ProductionProviderNotConfigured):
        service.run_inspection(db, s.id, T1)  # resolves server_vlm, unconfigured


def test_unconfigured_inspect_raises_not_configured():
    provider = ServerVLMInspectionProvider(base_url="")
    req = DetectionInspectionRequest("dp", "visual", {}, ["s3://a.jpg"])
    with pytest.raises(ProductionProviderNotConfigured):
        provider.inspect(req)


# ── Malformed output fails closed ────────────────────────────────────────────


@pytest.mark.parametrize("bad", [
    "not-a-dict",
    {"disposition": "pass_recommended"},           # missing fields
    dict(_good_response(), disposition="approve"),  # invalid disposition
    dict(_good_response(), evidence_regions="x"),   # wrong type
    dict(_good_response(), confidence="high"),      # non-numeric
])
def test_malformed_provider_output_rejected(bad):
    with pytest.raises(ValueError):
        parse_provider_response(bad)


def test_malformed_backend_output_fails_run_closed(db):
    _l2_ready(db)
    s = _session_with_capture(db)
    provider = _ConfiguredServerProvider({"disposition": "pass_recommended"})  # missing fields
    run = service.run_inspection(db, s.id, T1, provider=provider)
    assert run.status == "failed"
    assert service.list_detection_results(db, run.id, T1) == []


def test_backend_transport_error_fails_run_closed(db):
    _l2_ready(db)
    s = _session_with_capture(db)
    provider = _ConfiguredServerProvider(RuntimeError("connection refused"))
    run = service.run_inspection(db, s.id, T1, provider=provider)
    assert run.status == "failed"


# ── Happy path: evidence + raw response persisted ────────────────────────────


def test_valid_backend_output_persists_evidence_and_raw_response(db):
    _l2_ready(db)
    s = _session_with_capture(db)
    provider = _ConfiguredServerProvider(_good_response(evidence=[{"bbox": [10, 20, 30, 40]}]))
    run = service.run_inspection(db, s.id, T1, provider=provider)
    assert run.status == "completed"
    results = service.list_detection_results(db, run.id, T1)
    visual = [r for r in results if r.checkpoint_category == "visual"]
    assert visual and visual[0].evidence_regions_json == [{"bbox": [10, 20, 30, 40]}]
    # Raw provider response stored verbatim for audit.
    assert visual[0].raw_provider_response_json["model"] == "qwen3.5-vl-8b-int4"
    assert visual[0].provider == "server_vlm"


def test_missing_evidence_forces_review_with_real_provider(db):
    _l2_ready(db, confirmed_content={"evidence_required": ["seam close-up"]})
    s = _session_with_capture(db)
    provider = _ConfiguredServerProvider(_good_response(disposition="pass_recommended", evidence=[]))
    run = service.run_inspection(db, s.id, T1, provider=provider)
    visual = [r for r in service.list_detection_results(db, run.id, T1) if r.checkpoint_category == "visual"]
    assert visual and all(r.disposition == "review_required" for r in visual)


# ── Mock cannot be selected in production mode ────────────────────────────────


def test_mock_cannot_be_selected_in_production_mode(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "mock")
    with pytest.raises(ProductionProviderNotConfigured):
        get_production_inspection_provider()


def test_server_provider_selected_when_configured(monkeypatch):
    monkeypatch.setenv("QC_PRODUCTION_INSPECTION_PROVIDER", "server_vlm")
    monkeypatch.setenv("QC_SERVER_VLM_BASE_URL", "https://vlm.internal")
    provider = get_production_inspection_provider()
    assert isinstance(provider, ServerVLMInspectionProvider)
    assert provider.is_configured is True
    assert provider.model_name == "qwen3.5-vl-8b-int4"


# ── Server profile for learning + tablet_mnn blocked ─────────────────────────


def test_server_profile_selected_for_learning():
    from src.qc_model.sample_learning.provider import Qwen35VLSampleLearningProvider
    from src.qc_model.runtime_profiles import RuntimeEnvironment, get_runtime_profile
    p = Qwen35VLSampleLearningProvider()
    assert p.model_name == get_runtime_profile(RuntimeEnvironment.SERVER.value).model
    assert p.model_name == "qwen3.5-vl-8b-int4"


def test_tablet_runtime_cannot_generate_production_rules(monkeypatch):
    from src.qc_model.production.runtime import assert_server_side_runtime
    monkeypatch.setenv("QC_VISION_RUNTIME_ENV", "tablet_mnn")
    with pytest.raises(TabletRuntimeNotAllowedForProduction):
        assert_server_side_runtime()


def test_tablet_runtime_blocks_production_run(db, monkeypatch):
    _l2_ready(db)
    s = _session_with_capture(db)
    monkeypatch.setenv("QC_VISION_RUNTIME_ENV", "tablet_mnn")
    provider = _ConfiguredServerProvider(_good_response())
    with pytest.raises(TabletRuntimeNotAllowedForProduction):
        service.run_inspection(db, s.id, T1, provider=provider)


def test_server_runtime_allows_production_run(db, monkeypatch):
    _l2_ready(db)
    s = _session_with_capture(db)
    monkeypatch.setenv("QC_VISION_RUNTIME_ENV", "server")
    provider = _ConfiguredServerProvider(_good_response())
    run = service.run_inspection(db, s.id, T1, provider=provider)
    assert run.status == "completed"
