"""Production deployment hardening tests (PR 29)."""
from __future__ import annotations

import os
import subprocess
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
        return subprocess.run(["alembic", *args], cwd=REPO_ROOT, env=env,
                              capture_output=True, text=True)

    assert alembic("upgrade", "head").returncode == 0
    assert alembic("downgrade", "base").returncode == 0
    up = alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
