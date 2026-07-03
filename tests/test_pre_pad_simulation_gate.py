"""Pre-Pad simulation gate.

Proves the non-physical layers are stable before any physical Android Pad
deployment. This is about system correctness, NOT synthetic image generation.

Surfaces exercised:
  * Server/API inspection-job lifecycle (SKU → standard revision → photos →
    detection points → job snapshot → media → model output → checkpoints →
    findings → final report).
  * Fail-closed policy (no detection points / no standard photos / empty or
    contradictory model output can never produce a pass).
  * Tenant isolation (cross-tenant access returns 404).
  * Legacy /api/v1/qc/inspect guard (SKU mismatch rejected; missing inputs
    return review_required, never pass).

Physical Pad testing remains explicitly deferred.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.db.models import Base
import src.db.qc_models          # noqa: F401 — register tables
import src.db.sku_models         # noqa: F401 — register tables
import src.db.execution_models   # noqa: F401 — register tables
import src.db.intake_models      # noqa: F401 — register tables

from src.db.sku_models import QCDetectionPoint, QCSkuItem, QCStandardPhoto
from src.db.execution_models import QCCheckpointResult, QCIncidentalFinding, QCModelResult
from src.db.seed_data import seed_flower_brooch

from src.api.deps import get_db_dep
from tests._auth_override import install_api_auth_override
from src.api.main import app

from src.inspection.service import (
    confirm_standard_revision,
    create_inspection_job,
    create_standard_revision,
    finalize_job,
    get_active_detection_points_for_job,
    submit_checkpoint_result,
    submit_incidental_finding,
)
from src.inspection.api_service import (
    attach_inspection_media,
    ingest_model_output,
)

from src.qwen.router import QwenRouter
from src.qwen.parser import parse_qwen_output
from src.qwen.service import QwenQCService
from src.qwen.dashscope_provider import DashScopeQwenProvider
from src.qwen.schema import (
    CapturePhotoInput,
    InspectionContext,
    QcPointInput,
    StandardPhotoInput,
)

TENANT = "tenant_gate"
OTHER_TENANT = "tenant_intruder"


# ── DB fixtures ──────────────────────────────────────────────────────────────


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


# ── HTTP fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def http_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def http_session_factory(http_engine):
    return sessionmaker(bind=http_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="module")
def client(http_session_factory):
    def override_get_db():
        session = http_session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db_dep] = override_get_db
    install_api_auth_override(app)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _uid() -> str:
    return uuid.uuid4().hex


def _make_sku(db, item_number: str, tenant_id: str = TENANT) -> QCSkuItem:
    sku = QCSkuItem(
        id=_uid(),
        tenant_id=tenant_id,
        item_number=item_number,
        name="Gate SKU",
        status="active",
    )
    db.add(sku)
    db.commit()
    db.refresh(sku)
    return sku


def _attach_standard_photo(db, sku_id, revision_id, tenant_id=TENANT, local_path="/factory/std.jpg"):
    photo = QCStandardPhoto(
        id=_uid(),
        tenant_id=tenant_id,
        sku_id=sku_id,
        standard_revision_id=revision_id,
        local_path=local_path,
        is_primary=True,
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)
    return photo


def _add_detection_point(db, sku_id, revision_id, code, tenant_id=TENANT, severity="major", is_active=True):
    dp = QCDetectionPoint(
        id=_uid(),
        tenant_id=tenant_id,
        sku_id=sku_id,
        standard_revision_id=revision_id,
        point_code=code,
        label=code.replace("_", " ").title(),
        severity=severity,
        sort_order=1,
        is_active=is_active,
    )
    db.add(dp)
    db.commit()
    db.refresh(dp)
    return dp


def _qc_point(qc_point_id="p1", code="COLOR") -> QcPointInput:
    return QcPointInput(
        qc_point_id=qc_point_id,
        qc_point_code=code,
        name="Color",
        description="Color must match the standard",
    )


def _context() -> InspectionContext:
    return InspectionContext(
        tenant_id=TENANT, sku_id="SKU-1", standard_id="STD-1", inspection_id="INS-1"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. Server/API inspection-job lifecycle simulation
# ══════════════════════════════════════════════════════════════════════════════


class TestServerLifecycleSimulation:
    """Drives the full non-physical lifecycle and proves each stage persists."""

    def _setup_full_standard(self, db, item_number, codes=("COLOR", "SHAPE")):
        sku = _make_sku(db, item_number)
        rev = create_standard_revision(db, sku.id, TENANT, created_from="seed")
        _attach_standard_photo(db, sku.id, rev.id)
        for code in codes:
            _add_detection_point(db, sku.id, rev.id, code)
        confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id=TENANT)
        return sku, rev

    def test_sku_standard_photos_and_points_attach_to_active_revision(self, db):
        sku, rev = self._setup_full_standard(db, "GATE-LIFECYCLE-1")
        # Standard photo persisted against the revision
        photos = db.query(QCStandardPhoto).filter_by(standard_revision_id=rev.id).all()
        assert len(photos) == 1
        # Detection points persisted, active, scoped to the revision
        points = (
            db.query(QCDetectionPoint)
            .filter_by(standard_revision_id=rev.id, is_active=True)
            .all()
        )
        assert {p.point_code for p in points} == {"COLOR", "SHAPE"}

    def test_job_snapshots_revision_and_full_pass_flow(self, db):
        sku, rev = self._setup_full_standard(db, "GATE-LIFECYCLE-2")
        job = create_inspection_job(db, sku.id, TENANT, job_ref="JOB-PASS")
        assert job.active_standard_revision_id == rev.id

        media = attach_inspection_media(db, job.id, local_path="/cap/a.jpg", tenant_id=TENANT)
        assert media.job_id == job.id

        model_result = ingest_model_output(
            db,
            job_id=job.id,
            provider="cloud_qwen",
            model_name="qwen-test",
            media_id=media.id,
            raw_output={
                "checkpoint_results": [
                    {"point_code": "COLOR", "result": "pass", "confidence": 0.97},
                    {"point_code": "SHAPE", "result": "pass", "confidence": 0.95},
                ],
                "incidental_findings": [],
            },
            tenant_id=TENANT,
        )
        # Model output + checkpoints persisted
        assert db.query(QCModelResult).filter_by(id=model_result.id).one()
        checkpoints = db.query(QCCheckpointResult).filter_by(job_id=job.id).all()
        assert len(checkpoints) == 2

        report = finalize_job(db, job.id, tenant_id=TENANT)
        assert report.overall_result == "pass"
        assert report.checkpoint_results_count == 2

    def test_serious_incidental_finding_forces_review_required(self, db):
        sku, rev = self._setup_full_standard(db, "GATE-LIFECYCLE-3")
        job = create_inspection_job(db, sku.id, TENANT)
        ingest_model_output(
            db,
            job_id=job.id,
            provider="cloud_qwen",
            model_name="qwen-test",
            raw_output={
                "checkpoint_results": [
                    {"point_code": "COLOR", "result": "pass"},
                    {"point_code": "SHAPE", "result": "pass"},
                ],
                "incidental_findings": [
                    {"severity": "major", "description": "Unexpected scratch on surface"},
                ],
            },
            tenant_id=TENANT,
        )
        assert db.query(QCIncidentalFinding).filter_by(job_id=job.id).count() == 1
        report = finalize_job(db, job.id, tenant_id=TENANT)
        assert report.overall_result == "review_required"

    def test_explicit_checkpoint_fail_yields_fail(self, db):
        sku, rev = self._setup_full_standard(db, "GATE-LIFECYCLE-4")
        job = create_inspection_job(db, sku.id, TENANT)
        ingest_model_output(
            db,
            job_id=job.id,
            provider="cloud_qwen",
            model_name="qwen-test",
            raw_output={
                "checkpoint_results": [
                    {"point_code": "COLOR", "result": "fail"},
                    {"point_code": "SHAPE", "result": "pass"},
                ],
                "incidental_findings": [],
            },
            tenant_id=TENANT,
        )
        report = finalize_job(db, job.id, tenant_id=TENANT)
        assert report.overall_result == "fail"

    def test_low_confidence_checkpoint_yields_review_required(self, db):
        sku, rev = self._setup_full_standard(db, "GATE-LIFECYCLE-5")
        job = create_inspection_job(db, sku.id, TENANT)
        ingest_model_output(
            db,
            job_id=job.id,
            provider="cloud_qwen",
            model_name="qwen-test",
            raw_output={
                "checkpoint_results": [
                    {"point_code": "COLOR", "result": "pass"},
                    {"point_code": "SHAPE", "result": "low_confidence"},
                ],
                "incidental_findings": [],
            },
            tenant_id=TENANT,
        )
        report = finalize_job(db, job.id, tenant_id=TENANT)
        assert report.overall_result == "review_required"

    def test_missing_checkpoint_becomes_missing_and_blocks_pass(self, db):
        sku, rev = self._setup_full_standard(db, "GATE-LIFECYCLE-6")
        job = create_inspection_job(db, sku.id, TENANT)
        # Only one of two points reported by the model
        ingest_model_output(
            db,
            job_id=job.id,
            provider="cloud_qwen",
            model_name="qwen-test",
            raw_output={
                "checkpoint_results": [{"point_code": "COLOR", "result": "pass"}],
                "incidental_findings": [],
            },
            tenant_id=TENANT,
        )
        report = finalize_job(db, job.id, tenant_id=TENANT)
        # The unreported point is auto-inserted as 'missing' → cannot pass
        results = db.query(QCCheckpointResult).filter_by(job_id=job.id).all()
        assert any(cr.result == "missing" for cr in results)
        assert report.overall_result == "review_required"


# ══════════════════════════════════════════════════════════════════════════════
# 2. Fail-closed guarantees
# ══════════════════════════════════════════════════════════════════════════════


class TestFailClosed:
    def test_no_pass_without_active_detection_points(self, db):
        """A confirmed revision with zero detection points cannot pass."""
        sku = _make_sku(db, "GATE-NO-POINTS")
        rev = create_standard_revision(db, sku.id, TENANT)
        _attach_standard_photo(db, sku.id, rev.id)
        confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id=TENANT)
        job = create_inspection_job(db, sku.id, TENANT)
        assert get_active_detection_points_for_job(db, job.id) == []
        report = finalize_job(db, job.id, tenant_id=TENANT)
        assert report.overall_result == "review_required"

    def test_no_inspection_pass_without_standard_photos(self, monkeypatch, tmp_path):
        """The model path fails closed when there are no standard photos."""
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        monkeypatch.setenv("ALLOW_SEND_IMAGES_TO_CLOUD_QWEN", "true")
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
        capture = tmp_path / "cap.png"
        capture.write_bytes(b"fake-image")

        result = QwenRouter().route(
            standard_photos=[],
            captured_photo=CapturePhotoInput(photo_id="cap-1", local_path=str(capture)),
            qc_points=[_qc_point()],
            context=_context(),
            cloud_provider=DashScopeQwenProvider(),
        )
        assert result.overall_result == "review_required"

    def test_empty_model_output_returns_review_required(self, db):
        """No checkpoint results at all → every point missing → review_required."""
        sku = _make_sku(db, "GATE-EMPTY-OUTPUT")
        rev = create_standard_revision(db, sku.id, TENANT)
        _attach_standard_photo(db, sku.id, rev.id)
        _add_detection_point(db, sku.id, rev.id, "COLOR")
        confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id=TENANT)
        job = create_inspection_job(db, sku.id, TENANT)
        ingest_model_output(
            db,
            job_id=job.id,
            provider="cloud_qwen",
            model_name="qwen-test",
            raw_output={"checkpoint_results": [], "incidental_findings": []},
            tenant_id=TENANT,
        )
        report = finalize_job(db, job.id, tenant_id=TENANT)
        assert report.overall_result == "review_required"

    def test_unknown_point_code_rejected(self, db):
        sku = _make_sku(db, "GATE-UNKNOWN-CODE")
        rev = create_standard_revision(db, sku.id, TENANT)
        _add_detection_point(db, sku.id, rev.id, "COLOR")
        confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id=TENANT)
        job = create_inspection_job(db, sku.id, TENANT)
        with pytest.raises(ValueError, match="Unknown point_code"):
            ingest_model_output(
                db,
                job_id=job.id,
                provider="cloud_qwen",
                model_name="qwen-test",
                raw_output={
                    "checkpoint_results": [{"point_code": "GHOST", "result": "pass"}],
                    "incidental_findings": [],
                },
                tenant_id=TENANT,
            )

    def test_duplicate_point_code_rejected(self, db):
        sku = _make_sku(db, "GATE-DUP-CODE")
        rev = create_standard_revision(db, sku.id, TENANT)
        _add_detection_point(db, sku.id, rev.id, "COLOR")
        confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id=TENANT)
        job = create_inspection_job(db, sku.id, TENANT)
        with pytest.raises(ValueError, match="Duplicate point_code"):
            ingest_model_output(
                db,
                job_id=job.id,
                provider="cloud_qwen",
                model_name="qwen-test",
                raw_output={
                    "checkpoint_results": [
                        {"point_code": "COLOR", "result": "pass"},
                        {"point_code": "COLOR", "result": "fail"},
                    ],
                    "incidental_findings": [],
                },
                tenant_id=TENANT,
            )

    def test_invalid_checkpoint_result_rejected(self, db):
        sku = _make_sku(db, "GATE-INVALID-RESULT")
        rev = create_standard_revision(db, sku.id, TENANT)
        _add_detection_point(db, sku.id, rev.id, "COLOR")
        confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id=TENANT)
        job = create_inspection_job(db, sku.id, TENANT)
        with pytest.raises(ValueError, match="Invalid checkpoint result"):
            ingest_model_output(
                db,
                job_id=job.id,
                provider="cloud_qwen",
                model_name="qwen-test",
                raw_output={
                    "checkpoint_results": [{"point_code": "COLOR", "result": "definitely_pass"}],
                    "incidental_findings": [],
                },
                tenant_id=TENANT,
            )

    def test_submit_checkpoint_rejects_invalid_result(self, db):
        sku = _make_sku(db, "GATE-SUBMIT-INVALID")
        rev = create_standard_revision(db, sku.id, TENANT)
        dp = _add_detection_point(db, sku.id, rev.id, "COLOR")
        confirm_standard_revision(db, rev.id, confirmed_by="alice", tenant_id=TENANT)
        job = create_inspection_job(db, sku.id, TENANT)
        with pytest.raises(ValueError, match="Invalid checkpoint result"):
            submit_checkpoint_result(
                db, job_id=job.id, detection_point_id=dp.id, result="great", tenant_id=TENANT
            )

    def test_parser_contradiction_cannot_produce_pass(self):
        """Model claims overall pass but an item is fail → recomputed to fail."""
        raw = (
            '{"overall_result": "pass", "confidence": 0.99, "model_name": "qwen",'
            ' "items": ['
            '   {"qc_point_id": "p1", "result": "pass"},'
            '   {"qc_point_id": "p2", "result": "fail"}'
            ' ]}'
        )
        out = parse_qwen_output(raw, expected_qc_point_ids=["p1", "p2"], engine="cloud_qwen")
        assert out.overall_result == "fail"

    def test_parser_missing_point_cannot_produce_pass(self):
        """Model claims overall pass but omits an expected point → review_required."""
        raw = (
            '{"overall_result": "pass", "confidence": 0.99, "model_name": "qwen",'
            ' "items": [{"qc_point_id": "p1", "result": "pass"}]}'
        )
        out = parse_qwen_output(raw, expected_qc_point_ids=["p1", "p2"], engine="cloud_qwen")
        assert out.overall_result == "review_required"

    def test_fake_provider_cannot_run_outside_test_harness(self, monkeypatch, tmp_path):
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("QC_ALLOW_TEST_ADAPTER", raising=False)
        monkeypatch.setenv("QC_ENGINE_MODE", "fake")
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        capture = tmp_path / "cap.png"
        capture.write_bytes(b"fake-image")
        standard = tmp_path / "std.png"
        standard.write_bytes(b"fake-image")

        result = QwenQCService().run_inspection(
            standard_photos=[StandardPhotoInput(photo_id="s1", local_path=str(standard))],
            captured_photo=CapturePhotoInput(photo_id="c1", local_path=str(capture)),
            qc_points=[_qc_point()],
            context=_context(),
        )
        assert result.overall_result == "review_required"
        assert result.engine != "fake_cloud_qwen"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Tenant isolation (cross-tenant access returns 404)
# ══════════════════════════════════════════════════════════════════════════════


class TestTenantIsolation:
    @pytest.fixture(autouse=True)
    def setup_job(self, client, http_session_factory):
        session = http_session_factory()
        try:
            sku = seed_flower_brooch(session, tenant_id=TENANT)
            self.sku_id = sku.id
        finally:
            session.close()
        resp = client.post(
            "/api/v1/qc/inspection-jobs",
            json={"tenant_id": TENANT, "sku_id": self.sku_id, "job_ref": "ISO-JOB"},
        )
        assert resp.status_code == 201, resp.text
        self.job_id = resp.json()["id"]

    def test_get_job_cross_tenant_404(self, client):
        r = client.get(
            f"/api/v1/qc/inspection-jobs/{self.job_id}", params={"tenant_id": OTHER_TENANT}
        )
        assert r.status_code == 404

    def test_add_media_cross_tenant_404(self, client):
        r = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/media",
            json={"tenant_id": OTHER_TENANT, "image_url": "http://x.invalid/a.jpg"},
        )
        assert r.status_code == 404

    def test_ingest_model_results_cross_tenant_404(self, client):
        r = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/model-results",
            json={
                "tenant_id": OTHER_TENANT,
                "provider": "cloud_qwen",
                "model_name": "qwen-test",
                "raw_output": {"checkpoint_results": [], "incidental_findings": []},
            },
        )
        assert r.status_code == 404

    def test_submit_checkpoint_cross_tenant_404(self, client):
        r = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/checkpoint-results",
            json={"tenant_id": OTHER_TENANT, "detection_point_id": "x", "result": "pass"},
        )
        assert r.status_code == 404

    def test_submit_finding_cross_tenant_404(self, client):
        r = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/incidental-findings",
            json={"tenant_id": OTHER_TENANT, "description": "probe", "severity": "minor"},
        )
        assert r.status_code == 404

    def test_finalize_cross_tenant_404(self, client):
        r = client.post(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/finalize",
            json={"tenant_id": OTHER_TENANT},
        )
        assert r.status_code == 404

    def test_report_cross_tenant_404(self, client):
        r = client.get(
            f"/api/v1/qc/inspection-jobs/{self.job_id}/report", params={"tenant_id": OTHER_TENANT}
        )
        assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# 4. Legacy /api/v1/qc/inspect guard
# ══════════════════════════════════════════════════════════════════════════════


class TestLegacyInspectGuard:
    SKU = "GATE-LEGACY-SKU"
    OTHER_SKU = "GATE-LEGACY-OTHER"

    def _make_standard(self, client, sku_id, with_point=True):
        std = client.post(
            "/api/v1/qc/standards",
            json={"tenant_id": TENANT, "sku_id": sku_id, "name": "Legacy Std"},
        ).json()
        if with_point:
            client.post(
                f"/api/v1/qc/standards/{std['id']}/qc-points",
                json={
                    "tenant_id": TENANT,
                    "qc_point_code": "COLOR",
                    "name": "Color",
                    "description": "Color must match",
                },
            )
        return std["id"]

    def _make_capture(self, client, sku_id, tmp_path):
        img = tmp_path / f"cap_{uuid.uuid4().hex}.jpg"
        img.write_bytes(b"\x00" * 32)
        return client.post(
            "/api/v1/qc/captures",
            json={"tenant_id": TENANT, "sku_id": sku_id, "local_path": str(img)},
        ).json()["id"]

    def test_standard_sku_mismatch_rejected(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        std_id = self._make_standard(client, self.OTHER_SKU)
        cap_id = self._make_capture(client, self.SKU, tmp_path)
        r = client.post(
            "/api/v1/qc/inspect",
            json={
                "tenant_id": TENANT,
                "sku_id": self.SKU,
                "standard_id": std_id,
                "capture_photo_id": cap_id,
            },
        )
        assert r.status_code == 400
        assert "sku_id" in r.text

    def test_capture_sku_mismatch_rejected(self, client, tmp_path, monkeypatch):
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "false")
        std_id = self._make_standard(client, self.SKU)
        cap_id = self._make_capture(client, self.OTHER_SKU, tmp_path)
        r = client.post(
            "/api/v1/qc/inspect",
            json={
                "tenant_id": TENANT,
                "sku_id": self.SKU,
                "standard_id": std_id,
                "capture_photo_id": cap_id,
            },
        )
        assert r.status_code == 400
        assert "sku_id" in r.text

    def test_missing_qc_points_returns_review_required_never_pass(self, client, tmp_path, monkeypatch):
        # Standard with NO qc-points; even if a provider were configured, never pass.
        monkeypatch.setenv("QC_ENGINE_MODE", "fake")
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        std_id = self._make_standard(client, self.SKU, with_point=False)
        cap_id = self._make_capture(client, self.SKU, tmp_path)
        r = client.post(
            "/api/v1/qc/inspect",
            json={
                "tenant_id": TENANT,
                "sku_id": self.SKU,
                "standard_id": std_id,
                "capture_photo_id": cap_id,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["result"]["overall_result"] == "review_required"

    def test_missing_standard_photos_returns_review_required_never_pass(self, client, tmp_path, monkeypatch):
        # Standard HAS a qc-point but NO standard photos; never pass.
        monkeypatch.setenv("QC_ENGINE_MODE", "fake")
        monkeypatch.setenv("QWEN_CLOUD_ENABLED", "true")
        std_id = self._make_standard(client, self.SKU, with_point=True)
        cap_id = self._make_capture(client, self.SKU, tmp_path)
        r = client.post(
            "/api/v1/qc/inspect",
            json={
                "tenant_id": TENANT,
                "sku_id": self.SKU,
                "standard_id": std_id,
                "capture_photo_id": cap_id,
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["result"]["overall_result"] == "review_required"
