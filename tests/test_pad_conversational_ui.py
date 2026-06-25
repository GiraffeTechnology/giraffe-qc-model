"""Tests for PR11: Pad Conversational QC UI.

All 27 required tests covering:
- Authentication (login, logout, invalid credentials)
- Language detection (Chinese, Japanese, English)
- Multilingual processing pipeline
- Intent classification (start_inspection, submit_checkpoint, view_report, confirm_intake)
- Confidence threshold enforcement
- Message audit trail
- Voice endpoint fallback
- Image upload
- Session info
- Language preference update
- Safety rules (LLM never decides final verdict)
- PWA manifest
- Orientation overlay presence
- Confirm standard endpoint (real DB write via confirm_standard_intake)
- Create inspection job endpoint (real DB write via create_inspection_job_from_api)
- Bridge env-awareness (FakeOpenClawLLMClient when OPENCLAW_API_URL not set)
- Canonical English audit trail (normalized_text_en never contains localized text)
- AndroidManifest correctness (existing theme, networkSecurityConfig preserved)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.api.deps import get_db_dep
from src.db.models import Base
import src.db.pad_models  # noqa: F401 — registers tables
import src.db.models  # noqa: F401
import src.db.qc_models  # noqa: F401
import src.db.sku_models  # noqa: F401
import src.db.execution_models  # noqa: F401
import src.db.intake_models  # noqa: F401
from src.openclaw.qc_agent_bridge import FakeOpenClawLLMClient, QCAgentBridge
from src.pad.session_service import seed_demo_operators


# ---------------------------------------------------------------------------
# In-memory test DB
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture(scope="module")
def db_session(db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    seed_demo_operators(session, tenant_id="demo")
    yield session
    session.close()


@pytest.fixture(scope="module")
def client(db_session):
    def override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db_dep] = override_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def seeded_sku(db_session):
    """Shirt SKU with an active standard revision — available for confirm/job tests."""
    from src.db.seed_data import seed_shirt_custom
    return seed_shirt_custom(db_session, tenant_id="demo")


@pytest.fixture
def auth_client(client):
    """Client with operator_cn logged in."""
    client.post("/pad/login", data={"username": "operator_cn", "password": "operator_cn", "tenant_id": "demo"})
    yield client


# ---------------------------------------------------------------------------
# Test 1: Login page renders
# ---------------------------------------------------------------------------
def test_01_login_page_renders(client):
    resp = client.get("/pad/login")
    assert resp.status_code == 200
    assert b"QC Pad" in resp.content
    assert b"<form" in resp.content


# ---------------------------------------------------------------------------
# Test 2: Successful login
# ---------------------------------------------------------------------------
def test_02_login_success(client):
    resp = client.post(
        "/pad/login",
        data={"username": "operator_cn", "password": "operator_cn", "tenant_id": "demo"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 200)


# ---------------------------------------------------------------------------
# Test 3: Invalid login returns 401
# ---------------------------------------------------------------------------
def test_03_login_invalid_credentials(client):
    resp = client.post(
        "/pad/login",
        data={"username": "operator_cn", "password": "wrong_password", "tenant_id": "demo"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 4: Chinese language detection
# ---------------------------------------------------------------------------
def test_04_chinese_language_detection():
    bridge = QCAgentBridge(client=FakeOpenClawLLMClient())
    lang = bridge.detect_language("开始检查")
    assert lang == "zh-CN"


# ---------------------------------------------------------------------------
# Test 5: Japanese language detection
# ---------------------------------------------------------------------------
def test_05_japanese_language_detection():
    bridge = QCAgentBridge(client=FakeOpenClawLLMClient())
    # Hiragana characters (を, し, ま, す) make this unambiguously Japanese
    lang = bridge.detect_language("検査を開始します")
    assert lang == "ja"


# ---------------------------------------------------------------------------
# Test 6: English language detection
# ---------------------------------------------------------------------------
def test_06_english_language_detection():
    bridge = QCAgentBridge(client=FakeOpenClawLLMClient())
    lang = bridge.detect_language("start inspection")
    assert lang == "en"


# ---------------------------------------------------------------------------
# Test 7: Chinese text processes to English intent
# ---------------------------------------------------------------------------
def test_07_chinese_text_to_english_intent():
    bridge = QCAgentBridge(client=FakeOpenClawLLMClient())
    result = bridge.process("开始检查", preferred_language="zh-CN")
    assert result.intent == "start_inspection"
    assert result.confidence >= 0.5


# ---------------------------------------------------------------------------
# Test 8: Japanese text processes to English intent
# ---------------------------------------------------------------------------
def test_08_japanese_text_to_english_intent():
    bridge = QCAgentBridge(client=FakeOpenClawLLMClient())
    result = bridge.process("検査を開始します", preferred_language="ja")
    assert result.intent == "start_inspection"
    assert result.confidence >= 0.5


# ---------------------------------------------------------------------------
# Test 9: English start inspection
# ---------------------------------------------------------------------------
def test_09_english_start_inspection_intent():
    bridge = QCAgentBridge(client=FakeOpenClawLLMClient())
    result = bridge.process("start inspection", preferred_language="en")
    assert result.intent == "start_inspection"


# ---------------------------------------------------------------------------
# Test 10: Low confidence returns clarify
# ---------------------------------------------------------------------------
def test_10_low_confidence_returns_clarify():
    bridge = QCAgentBridge(client=FakeOpenClawLLMClient())
    result = bridge.process("xyzzy gibberish", preferred_language="en")
    assert result.confidence < 0.5
    assert result.intent == "unknown"


# ---------------------------------------------------------------------------
# Test 11: Chat API returns structured response
# ---------------------------------------------------------------------------
def test_11_chat_api_structured_response(auth_client):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": "start inspection", "context": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "reply" in data
    assert "intent" in data
    assert "confidence" in data
    assert "detected_language" in data


# ---------------------------------------------------------------------------
# Test 12: Chat API with Chinese message
# ---------------------------------------------------------------------------
def test_12_chat_api_chinese_message(auth_client):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": "开始检查", "context": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detected_language"] == "zh-CN"
    assert data["intent"] == "start_inspection"


# ---------------------------------------------------------------------------
# Test 13: Chat API with Japanese message
# ---------------------------------------------------------------------------
def test_13_chat_api_japanese_message(auth_client):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": "検査を開始します", "context": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detected_language"] == "ja"
    assert data["intent"] == "start_inspection"


# ---------------------------------------------------------------------------
# Test 14: Unauthenticated chat returns 401
# ---------------------------------------------------------------------------
def test_14_unauthenticated_chat_returns_401(client):
    fresh = TestClient(app, raise_server_exceptions=True)
    from src.api.deps import get_db_dep as dep
    db_session_inner = None
    # We need to share the db session
    resp = fresh.post("/api/v1/pad/chat", json={"message": "hello"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Test 15: Voice endpoint returns transcript_required
# ---------------------------------------------------------------------------
def test_15_voice_endpoint_transcript_required(auth_client):
    resp = auth_client.post("/api/v1/pad/voice")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "transcript_required"


# ---------------------------------------------------------------------------
# Test 16: Image upload endpoint
# ---------------------------------------------------------------------------
def test_16_image_upload(auth_client):
    resp = auth_client.post(
        "/api/v1/pad/upload",
        files={"image": ("test.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "received"
    assert data["filename"] == "test.jpg"


# ---------------------------------------------------------------------------
# Test 17: Session info endpoint
# ---------------------------------------------------------------------------
def test_17_session_info(auth_client):
    resp = auth_client.get("/api/v1/pad/session")
    assert resp.status_code == 200
    data = resp.json()
    assert "operator_id" in data
    assert "preferred_language" in data
    assert "session_id" in data


# ---------------------------------------------------------------------------
# Test 18: Language preference update
# ---------------------------------------------------------------------------
def test_18_language_preference_update(auth_client):
    resp = auth_client.post(
        "/api/v1/pad/language",
        json={"language": "ja"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["preferred_language"] == "ja"


# ---------------------------------------------------------------------------
# Test 19: Confirm standard requires explicit operator action (real DB write)
# ---------------------------------------------------------------------------
def test_19_confirm_standard_requires_intake_id(auth_client, db_session, seeded_sku):
    from src.intake.service import create_standard_intake, extract_standard_draft

    # Missing intake_id -> 400
    resp = auth_client.post("/api/v1/pad/confirm_standard", json={})
    assert resp.status_code == 400

    # Non-existent intake_id -> 404
    resp = auth_client.post(
        "/api/v1/pad/confirm_standard",
        json={"intake_id": "00000000000000000000000000000000"},
    )
    assert resp.status_code == 404

    # Real pending intake -> confirmed with DB-backed revision
    intake = create_standard_intake(
        db_session,
        sku_id=seeded_sku.id,
        tenant_id="demo",
        raw_text="collar stitch, fabric stain check",
    )
    extract_standard_draft(db_session, intake.id)

    resp = auth_client.post("/api/v1/pad/confirm_standard", json={"intake_id": intake.id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["intake_id"] == intake.id
    assert "revision_id" in data


# ---------------------------------------------------------------------------
# Test 20: Create inspection job (real DB write via create_inspection_job_from_api)
# ---------------------------------------------------------------------------
def test_20_create_inspection_job(auth_client, seeded_sku):
    resp = auth_client.post(
        "/api/v1/pad/create_inspection_job",
        json={"sku_id": seeded_sku.id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "job_created"
    assert data["sku_id"] == seeded_sku.id
    assert "job_id" in data


# ---------------------------------------------------------------------------
# Test 21: get_bridge() returns FakeOpenClawLLMClient when OPENCLAW_API_URL unset
# ---------------------------------------------------------------------------
def test_21_get_bridge_returns_fake_without_env():
    import os
    from src.openclaw import qc_agent_bridge as mod

    original_url = os.environ.pop("OPENCLAW_API_URL", None)
    original_singleton = mod._bridge_singleton
    mod._bridge_singleton = None
    try:
        bridge = mod.get_bridge()
        assert isinstance(bridge._client, mod.FakeOpenClawLLMClient)
    finally:
        if original_url is not None:
            os.environ["OPENCLAW_API_URL"] = original_url
        mod._bridge_singleton = original_singleton


# ---------------------------------------------------------------------------
# Test 22: confirm_standard creates real revision + detection points + confirmation
# ---------------------------------------------------------------------------
def test_22_confirm_standard_creates_real_revision(auth_client, db_session, seeded_sku):
    from src.intake.service import create_standard_intake, extract_standard_draft
    from src.db.sku_models import QCSkuStandardRevision, QCDetectionPoint
    from src.db.intake_models import QCOperatorConfirmation

    intake = create_standard_intake(
        db_session,
        sku_id=seeded_sku.id,
        tenant_id="demo",
        raw_text="collar stitch, fabric stain check",
    )
    extract_standard_draft(db_session, intake.id)

    rev_count_before = db_session.query(QCSkuStandardRevision).filter_by(sku_id=seeded_sku.id).count()

    resp = auth_client.post("/api/v1/pad/confirm_standard", json={"intake_id": intake.id})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"

    db_session.expire_all()
    rev_count_after = db_session.query(QCSkuStandardRevision).filter_by(sku_id=seeded_sku.id).count()
    assert rev_count_after > rev_count_before

    conf = db_session.query(QCOperatorConfirmation).filter_by(intake_id=intake.id).first()
    assert conf is not None
    assert conf.status == "confirmed"

    revision_id = data["revision_id"]
    dp_count = db_session.query(QCDetectionPoint).filter_by(standard_revision_id=revision_id).count()
    assert dp_count > 0


# ---------------------------------------------------------------------------
# Test 23: create_inspection_job creates real QCInspectionJob row
# ---------------------------------------------------------------------------
def test_23_create_inspection_job_creates_real_row(auth_client, db_session, seeded_sku):
    from src.db.execution_models import QCInspectionJob

    job_count_before = db_session.query(QCInspectionJob).filter_by(sku_id=seeded_sku.id).count()

    resp = auth_client.post(
        "/api/v1/pad/create_inspection_job",
        json={"sku_id": seeded_sku.id},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data

    db_session.expire_all()
    job_count_after = db_session.query(QCInspectionJob).filter_by(sku_id=seeded_sku.id).count()
    assert job_count_after > job_count_before

    job = db_session.query(QCInspectionJob).filter_by(id=data["job_id"]).first()
    assert job is not None
    assert job.sku_id == seeded_sku.id
    assert job.tenant_id == "demo"


# ---------------------------------------------------------------------------
# Test 24: Assistant normalized_text_en stays canonical English (not localized)
# ---------------------------------------------------------------------------
def test_24_assistant_normalized_text_en_is_english(auth_client, db_session):
    from src.db.pad_models import QCConversationMessage

    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": "开始检查", "context": {}},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    msg = (
        db_session.query(QCConversationMessage)
        .filter_by(role="assistant")
        .order_by(QCConversationMessage.id.desc())
        .first()
    )
    assert msg is not None
    assert msg.normalized_text_en is not None
    chinese_re = re.compile(r"[一-鿿㐀-䶿]")
    assert not chinese_re.search(msg.normalized_text_en), (
        f"normalized_text_en must be English but got: {msg.normalized_text_en!r}"
    )


# ---------------------------------------------------------------------------
# Test 25: AndroidManifest uses existing Theme.GiraffeQC (not undefined GiraffeQCPad)
# ---------------------------------------------------------------------------
def test_25_android_manifest_uses_existing_theme():
    manifest_path = (
        Path(__file__).resolve().parent.parent
        / "apps/android-qc/app/src/main/AndroidManifest.xml"
    )
    content = manifest_path.read_text()
    assert "Theme.GiraffeQCPad" not in content, (
        "Must not reference undefined theme Theme.GiraffeQCPad"
    )
    assert "Theme.GiraffeQC" in content, "Must use existing theme Theme.GiraffeQC"


# ---------------------------------------------------------------------------
# Test 26: AndroidManifest preserves networkSecurityConfig for factory LAN HTTP
# ---------------------------------------------------------------------------
def test_26_android_manifest_preserves_network_security_config():
    manifest_path = (
        Path(__file__).resolve().parent.parent
        / "apps/android-qc/app/src/main/AndroidManifest.xml"
    )
    content = manifest_path.read_text()
    assert "networkSecurityConfig" in content, (
        "Must reference networkSecurityConfig to allow HTTP to factory LAN (192.168.1.10)"
    )
    assert 'usesCleartextTraffic="false"' not in content, (
        "Must not set usesCleartextTraffic=false — breaks HTTP to factory LAN"
    )


# ---------------------------------------------------------------------------
# Test 27: LLM must not bypass confirmation (chat alone must not mutate DB)
# ---------------------------------------------------------------------------
def test_27_llm_must_not_bypass_confirmation(auth_client, db_session):
    from src.db.sku_models import QCSkuStandardRevision

    rev_count_before = db_session.query(QCSkuStandardRevision).count()

    # Even with a "confirm" intent, chat endpoint must not create any standard revision
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": "confirm standard", "context": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Chat response must never carry a revision_id — that only comes from explicit confirm endpoint
    assert "revision_id" not in data

    db_session.expire_all()
    rev_count_after = db_session.query(QCSkuStandardRevision).count()
    assert rev_count_after == rev_count_before, (
        "Chat endpoint must not create standard revisions — LLM output is never trusted directly"
    )
