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


# ---------------------------------------------------------------------------
# Test 28: Chinese fuzzy standard input returns standard_confirmation card
# ---------------------------------------------------------------------------
_ZH_STANDARD_MSG = (
    "这件衬衣检查纽扣7颗，领口线迹不能歪，布面不能有污渍，标签位置要对。"
)


def test_28_chinese_fuzzy_standard_input_creates_standard_confirmation_card(auth_client, seeded_sku):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _ZH_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["detected_language"] == "zh-CN"
    assert data["intent"] == "create_standard_intake"
    assert data["confidence"] >= 0.5
    assert data["requires_confirmation"] is True

    card = data["action_card"]
    assert card is not None
    assert card["type"] == "standard_confirmation"
    assert card["source_language"] == "zh-CN"
    assert "canonical_english_text" in card
    assert card["requires_confirmation"] is True

    codes = {cp["point_code"] for cp in card["checkpoints"]}
    assert "BUTTON_COUNT" in codes, f"Expected BUTTON_COUNT in {codes}"
    assert "COLLAR_STITCHING" in codes, f"Expected COLLAR_STITCHING in {codes}"
    assert "FABRIC_STAIN" in codes, f"Expected FABRIC_STAIN in {codes}"
    assert "LABEL_POSITION" in codes, f"Expected LABEL_POSITION in {codes}"

    btn = next(cp for cp in card["checkpoints"] if cp["point_code"] == "BUTTON_COUNT")
    assert btn["expected_value"] == "7", f"Expected BUTTON_COUNT expected_value=7, got {btn['expected_value']}"


# ---------------------------------------------------------------------------
# Test 29: Japanese fuzzy standard input returns standard_confirmation card
# ---------------------------------------------------------------------------
_JA_STANDARD_MSG = (
    "シャツのボタン7個、衿の縫い目は真っ直ぐ、生地の汚れなし、ラベルの位置正確。"
)


def test_29_japanese_fuzzy_standard_input_creates_standard_confirmation_card(auth_client, seeded_sku):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _JA_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["detected_language"] == "ja"
    assert data["intent"] == "create_standard_intake"
    assert data["confidence"] >= 0.5
    assert data["requires_confirmation"] is True

    card = data["action_card"]
    assert card is not None
    assert card["type"] == "standard_confirmation"
    assert card["source_language"] == "ja"
    assert card["requires_confirmation"] is True

    codes = {cp["point_code"] for cp in card["checkpoints"]}
    assert "BUTTON_COUNT" in codes, f"Expected BUTTON_COUNT in {codes}"
    assert "COLLAR_STITCHING" in codes, f"Expected COLLAR_STITCHING in {codes}"
    assert "FABRIC_STAIN" in codes, f"Expected FABRIC_STAIN in {codes}"
    assert "LABEL_POSITION" in codes, f"Expected LABEL_POSITION in {codes}"

    btn = next(cp for cp in card["checkpoints"] if cp["point_code"] == "BUTTON_COUNT")
    assert btn["expected_value"] == "7"


# ---------------------------------------------------------------------------
# Test 30: Chat with create_standard_intake creates QCStandardIntake (not revision)
# ---------------------------------------------------------------------------
def test_30_pad_chat_create_standard_intake_creates_qc_standard_intake_but_not_active_revision(
    auth_client, db_session, seeded_sku
):
    from src.db.intake_models import QCStandardIntake
    from src.db.sku_models import QCSkuStandardRevision

    intake_count_before = db_session.query(QCStandardIntake).filter_by(sku_id=seeded_sku.id).count()
    rev_count_before = db_session.query(QCSkuStandardRevision).filter_by(
        sku_id=seeded_sku.id, status="active"
    ).count()

    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _ZH_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    intake_count_after = db_session.query(QCStandardIntake).filter_by(sku_id=seeded_sku.id).count()
    rev_count_after = db_session.query(QCSkuStandardRevision).filter_by(
        sku_id=seeded_sku.id, status="active"
    ).count()

    assert intake_count_after > intake_count_before, "Chat must create a QCStandardIntake record"
    assert rev_count_after == rev_count_before, (
        "Chat must NOT create an active standard revision — operator confirmation required"
    )

    # Intake must be in pending_confirmation status
    intake = (
        db_session.query(QCStandardIntake)
        .filter_by(sku_id=seeded_sku.id)
        .order_by(QCStandardIntake.created_at.desc())
        .first()
    )
    assert intake is not None
    assert intake.status == "pending_confirmation"


# ---------------------------------------------------------------------------
# Test 31: Operator confirms standard_confirmation card → creates active revision
# ---------------------------------------------------------------------------
def test_31_standard_confirmation_card_confirm_creates_active_revision(
    auth_client, db_session, seeded_sku
):
    from src.db.sku_models import QCSkuStandardRevision

    # First: send Chinese standard text to create a pending intake
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _ZH_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    card = resp.json()["action_card"]
    intake_id = card["intake_id"]
    assert intake_id is not None

    rev_count_before = db_session.query(QCSkuStandardRevision).filter_by(sku_id=seeded_sku.id).count()

    # Operator confirms the action card
    resp2 = auth_client.post("/api/v1/pad/confirm_standard", json={"intake_id": intake_id})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "confirmed"
    assert "revision_id" in data2

    db_session.expire_all()
    rev_count_after = db_session.query(QCSkuStandardRevision).filter_by(sku_id=seeded_sku.id).count()
    assert rev_count_after > rev_count_before, "confirm_standard must create a new standard revision"


# ---------------------------------------------------------------------------
# Test 32: Fuzzy standard input preserves raw text and canonical English
# ---------------------------------------------------------------------------
def test_32_fuzzy_standard_input_preserves_raw_text_and_canonical_english(
    auth_client, db_session, seeded_sku
):
    from src.db.intake_models import QCStandardIntake

    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _ZH_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    intake = (
        db_session.query(QCStandardIntake)
        .filter_by(sku_id=seeded_sku.id)
        .order_by(QCStandardIntake.created_at.desc())
        .first()
    )
    assert intake is not None

    # Original Chinese must be preserved in raw_text
    assert intake.raw_text == _ZH_STANDARD_MSG, (
        f"raw_text must preserve original Chinese, got: {intake.raw_text!r}"
    )

    # Canonical English must be stored in normalized_text (no CJK characters)
    assert intake.normalized_text is not None
    chinese_re = re.compile(r"[一-鿿㐀-䶿]")
    assert not chinese_re.search(intake.normalized_text), (
        f"normalized_text must be English, got: {intake.normalized_text!r}"
    )
    assert "QC standard" in intake.normalized_text


# ---------------------------------------------------------------------------
# Test 33: Low-confidence standard input does not create intake
# ---------------------------------------------------------------------------
def test_33_low_confidence_standard_input_does_not_create_intake(auth_client, db_session, seeded_sku):
    from src.db.intake_models import QCStandardIntake

    intake_count_before = db_session.query(QCStandardIntake).count()

    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": "xyzzy gibberish 12345", "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["confidence"] < 0.5
    assert data["intent"] == "unknown"
    assert data["action_card"] is None

    db_session.expire_all()
    intake_count_after = db_session.query(QCStandardIntake).count()
    assert intake_count_after == intake_count_before, (
        "Low-confidence input must not create a QCStandardIntake record"
    )


# ---------------------------------------------------------------------------
# Test 34: standard_confirmation action card schema is stable
# ---------------------------------------------------------------------------
def test_34_action_card_schema_is_stable(auth_client, seeded_sku):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _ZH_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    card = resp.json()["action_card"]
    assert card is not None

    required_keys = {"type", "intake_id", "source_language", "canonical_english_text",
                     "checkpoints", "requires_confirmation"}
    missing = required_keys - card.keys()
    assert not missing, f"Action card missing required keys: {missing}"

    assert card["type"] == "standard_confirmation"
    assert isinstance(card["checkpoints"], list)
    assert len(card["checkpoints"]) >= 2

    cp_required = {"point_code", "label", "severity", "method_hint", "expected_value"}
    for cp in card["checkpoints"]:
        missing_cp = cp_required - cp.keys()
        assert not missing_cp, f"Checkpoint missing keys {missing_cp}: {cp}"


# ---------------------------------------------------------------------------
# Test 35: English fuzzy standard input creates standard_confirmation card
# ---------------------------------------------------------------------------
_EN_STANDARD_MSG = (
    "Check this shirt: 7 buttons, collar stitching not crooked, no fabric stains, "
    "label position correct."
)


def test_english_fuzzy_standard_input_creates_standard_confirmation_card(auth_client, seeded_sku):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _EN_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["detected_language"] == "en"
    assert data["intent"] == "create_standard_intake"
    assert data["confidence"] >= 0.5
    assert data["requires_confirmation"] is True

    card = data["action_card"]
    assert card is not None
    assert card["type"] == "standard_confirmation"
    assert card["source_language"] == "en"
    assert card["requires_confirmation"] is True

    codes = {cp["point_code"] for cp in card["checkpoints"]}
    assert "BUTTON_COUNT" in codes, f"Expected BUTTON_COUNT in {codes}"
    assert "COLLAR_STITCHING" in codes, f"Expected COLLAR_STITCHING in {codes}"
    assert "FABRIC_STAIN" in codes, f"Expected FABRIC_STAIN in {codes}"
    assert "LABEL_POSITION" in codes, f"Expected LABEL_POSITION in {codes}"

    btn = next(cp for cp in card["checkpoints"] if cp["point_code"] == "BUTTON_COUNT")
    assert btn["expected_value"] == "7", f"Expected BUTTON_COUNT expected_value=7, got {btn['expected_value']}"


# ---------------------------------------------------------------------------
# Test 36: Chinese fuzzy standard input (alias with required test name)
# ---------------------------------------------------------------------------
def test_chinese_fuzzy_standard_input_creates_standard_confirmation_card(auth_client, seeded_sku):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _ZH_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detected_language"] == "zh-CN"
    assert data["intent"] == "create_standard_intake"
    assert data["requires_confirmation"] is True
    card = data["action_card"]
    assert card["type"] == "standard_confirmation"
    codes = {cp["point_code"] for cp in card["checkpoints"]}
    assert {"BUTTON_COUNT", "COLLAR_STITCHING", "FABRIC_STAIN", "LABEL_POSITION"}.issubset(codes)


# ---------------------------------------------------------------------------
# Test 37: Japanese fuzzy standard input (alias with required test name)
# ---------------------------------------------------------------------------
def test_japanese_fuzzy_standard_input_creates_standard_confirmation_card(auth_client, seeded_sku):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _JA_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["detected_language"] == "ja"
    assert data["intent"] == "create_standard_intake"
    assert data["requires_confirmation"] is True
    card = data["action_card"]
    assert card["type"] == "standard_confirmation"
    codes = {cp["point_code"] for cp in card["checkpoints"]}
    assert {"BUTTON_COUNT", "COLLAR_STITCHING", "FABRIC_STAIN", "LABEL_POSITION"}.issubset(codes)


# ---------------------------------------------------------------------------
# Test 38: Chat creates intake but not active revision (required test name)
# ---------------------------------------------------------------------------
def test_pad_chat_create_standard_intake_creates_qc_standard_intake_but_not_active_revision(
    auth_client, db_session, seeded_sku
):
    from src.db.intake_models import QCStandardIntake
    from src.db.sku_models import QCSkuStandardRevision

    intake_count_before = db_session.query(QCStandardIntake).filter_by(sku_id=seeded_sku.id).count()
    rev_count_before = db_session.query(QCSkuStandardRevision).filter_by(
        sku_id=seeded_sku.id, status="active"
    ).count()

    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _EN_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    intake_count_after = db_session.query(QCStandardIntake).filter_by(sku_id=seeded_sku.id).count()
    rev_count_after = db_session.query(QCSkuStandardRevision).filter_by(
        sku_id=seeded_sku.id, status="active"
    ).count()

    assert intake_count_after > intake_count_before, "Chat must create a QCStandardIntake record"
    assert rev_count_after == rev_count_before, (
        "Chat must NOT create an active standard revision — operator confirmation required"
    )


# ---------------------------------------------------------------------------
# Test 39: Confirmation creates active revision (required test name)
# ---------------------------------------------------------------------------
def test_standard_confirmation_card_confirm_creates_active_revision(
    auth_client, db_session, seeded_sku
):
    from src.db.sku_models import QCSkuStandardRevision

    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _EN_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    card = resp.json()["action_card"]
    intake_id = card["intake_id"]
    assert intake_id is not None

    rev_count_before = db_session.query(QCSkuStandardRevision).filter_by(sku_id=seeded_sku.id).count()

    resp2 = auth_client.post("/api/v1/pad/confirm_standard", json={"intake_id": intake_id})
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["status"] == "confirmed"
    assert "revision_id" in data2

    db_session.expire_all()
    rev_count_after = db_session.query(QCSkuStandardRevision).filter_by(sku_id=seeded_sku.id).count()
    assert rev_count_after > rev_count_before, "confirm_standard must create a new standard revision"


# ---------------------------------------------------------------------------
# Test 40: Raw text preserved, canonical English stored separately (required test name)
# ---------------------------------------------------------------------------
def test_fuzzy_standard_input_preserves_raw_text_and_canonical_english(
    auth_client, db_session, seeded_sku
):
    from src.db.intake_models import QCStandardIntake

    # Use English input for this variant
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _EN_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200

    db_session.expire_all()
    intake = (
        db_session.query(QCStandardIntake)
        .filter_by(sku_id=seeded_sku.id)
        .order_by(QCStandardIntake.created_at.desc())
        .first()
    )
    assert intake is not None
    assert intake.raw_text == _EN_STANDARD_MSG, (
        f"raw_text must preserve original input, got: {intake.raw_text!r}"
    )
    assert intake.normalized_text is not None
    assert "QC standard" in intake.normalized_text, (
        f"normalized_text must contain QC standard canonical form, got: {intake.normalized_text!r}"
    )


# ---------------------------------------------------------------------------
# Test 41: Low-confidence input does not create intake (required test name)
# ---------------------------------------------------------------------------
def test_low_confidence_standard_input_does_not_create_intake(auth_client, db_session, seeded_sku):
    from src.db.intake_models import QCStandardIntake

    intake_count_before = db_session.query(QCStandardIntake).count()

    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": "xyzzy gibberish test 9999", "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["confidence"] < 0.5
    assert data["action_card"] is None

    db_session.expire_all()
    intake_count_after = db_session.query(QCStandardIntake).count()
    assert intake_count_after == intake_count_before, (
        "Low-confidence input must not create a QCStandardIntake record"
    )


# ---------------------------------------------------------------------------
# Test 42: Action card schema is stable (required test name)
# ---------------------------------------------------------------------------
def test_action_card_schema_is_stable(auth_client, seeded_sku):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _EN_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    card = resp.json()["action_card"]
    assert card is not None

    required_keys = {"type", "intake_id", "source_language", "canonical_english_text",
                     "checkpoints", "requires_confirmation"}
    missing = required_keys - card.keys()
    assert not missing, f"Action card missing required keys: {missing}"

    assert card["type"] == "standard_confirmation"
    assert isinstance(card["checkpoints"], list)
    assert len(card["checkpoints"]) >= 2

    cp_required = {"point_code", "label", "severity", "method_hint", "expected_value"}
    for cp in card["checkpoints"]:
        missing_cp = cp_required - cp.keys()
        assert not missing_cp, f"Checkpoint missing keys {missing_cp}: {cp}"


# ---------------------------------------------------------------------------
# Test 43: standard_confirmation card contains expected checkpoints (required test name)
# ---------------------------------------------------------------------------
def test_standard_confirmation_card_contains_expected_checkpoints(auth_client, seeded_sku):
    resp = auth_client.post(
        "/api/v1/pad/chat",
        json={"message": _EN_STANDARD_MSG, "context": {"sku_id": seeded_sku.id}},
    )
    assert resp.status_code == 200
    card = resp.json()["action_card"]
    assert card is not None
    assert card["type"] == "standard_confirmation"

    checkpoints = card["checkpoints"]
    codes = {cp["point_code"] for cp in checkpoints}
    assert "BUTTON_COUNT" in codes
    assert "COLLAR_STITCHING" in codes
    assert "FABRIC_STAIN" in codes
    assert "LABEL_POSITION" in codes

    btn = next(cp for cp in checkpoints if cp["point_code"] == "BUTTON_COUNT")
    assert btn["expected_value"] == "7"
    assert btn["severity"] == "critical"
    assert btn["method_hint"] == "counting"

    collar = next(cp for cp in checkpoints if cp["point_code"] == "COLLAR_STITCHING")
    assert collar["severity"] == "major"

    stain = next(cp for cp in checkpoints if cp["point_code"] == "FABRIC_STAIN")
    assert stain["severity"] == "major"

    label = next(cp for cp in checkpoints if cp["point_code"] == "LABEL_POSITION")
    assert label["severity"] == "minor"


# ---------------------------------------------------------------------------
# Test 44: Portrait overlay blocks standard_confirmation buttons (required test name)
# ---------------------------------------------------------------------------
def test_portrait_overlay_blocks_standard_confirmation_button():
    """The standard_confirmation confirm button has qc-action-btn class,
    which the portrait overlay JS disables when device is in portrait mode."""
    static_dir = Path(__file__).resolve().parent.parent / "src" / "web" / "static"
    templates_dir = Path(__file__).resolve().parent.parent / "src" / "web" / "templates"

    # Workspace template must have orientation overlay element
    workspace_html = (templates_dir / "pad_workspace.html").read_text()
    assert 'id="orientation-overlay"' in workspace_html, (
        "Template must have orientation overlay element"
    )

    # Orientation JS must disable qc-action-btn elements in portrait mode
    orientation_js = (static_dir / "pad_orientation.js").read_text()
    assert "qc-action-btn" in orientation_js, (
        "Orientation JS must reference qc-action-btn to disable action buttons in portrait"
    )
    assert "disabled" in orientation_js, (
        "Orientation JS must set disabled on action buttons in portrait mode"
    )

    # pad_chat.js must add qc-action-btn class to confirm button for standard_confirmation
    chat_js = (static_dir / "pad_chat.js").read_text()
    assert "standard_confirmation" in chat_js, (
        "pad_chat.js must handle standard_confirmation card type"
    )
    assert "qc-action-btn" in chat_js, (
        "pad_chat.js must assign qc-action-btn class to confirm button"
    )


def test_stage2_web_control_runs_real_job_to_final_report(
    auth_client, db_session, seeded_sku, tmp_path, monkeypatch
):
    """The browser-facing flow persists evidence, checkpoint rows and verdict."""
    monkeypatch.setenv("QC_STORAGE_ROOT", str(tmp_path))

    search = auth_client.get("/api/v1/pad/skus", params={"q": seeded_sku.item_number})
    assert search.status_code == 200
    assert any(item["id"] == seeded_sku.id for item in search.json()["items"])

    created = auth_client.post(
        "/api/v1/pad/create_inspection_job", json={"sku_id": seeded_sku.id}
    )
    assert created.status_code == 200
    job_id = created.json()["job_id"]

    no_evidence = auth_client.post(
        f"/api/v1/pad/inspection-jobs/{job_id}/checkpoint-results",
        json={"results": []},
    )
    assert no_evidence.status_code == 400
    assert "no attached evidence" in no_evidence.json()["error"]

    fixture = Path(__file__).parent / "fixtures" / "qc" / "capture_red_square_pass.png"
    attached = auth_client.post(
        f"/api/v1/pad/inspection-jobs/{job_id}/media",
        data={"capture_source": "mac_usb_camera"},
        files={"image": ("mac-usb-camera.png", fixture.read_bytes(), "image/png")},
    )
    assert attached.status_code == 201
    assert attached.json()["source"] == "mac_usb_camera"
    assert Path(
        db_session.query(src.db.execution_models.QCInspectionMedia)
        .filter_by(job_id=job_id)
        .one()
        .local_path
    ).exists()

    state = auth_client.get(f"/api/v1/pad/inspection-jobs/{job_id}").json()
    assert state["media_count"] == 1
    results = [
        {"detection_point_id": point["id"], "result": "pass", "confidence": 1.0}
        for point in state["checkpoints"]
    ]
    submitted = auth_client.post(
        f"/api/v1/pad/inspection-jobs/{job_id}/checkpoint-results",
        json={"results": results},
    )
    assert submitted.status_code == 200
    assert submitted.json()["count"] == len(results)

    finalized = auth_client.post(f"/api/v1/pad/inspection-jobs/{job_id}/finalize")
    assert finalized.status_code == 200
    assert finalized.json()["overall_result"] == "pass"

    final_state = auth_client.get(f"/api/v1/pad/inspection-jobs/{job_id}").json()
    assert final_state["status"] == "pass"
    assert final_state["final_report"]["overall_result"] == "pass"
    assert all(point["submitted_result"] == "pass" for point in final_state["checkpoints"])


def test_stage2_live_vision_endpoint_records_suggestions_without_auto_finalizing(
    auth_client, db_session, seeded_sku, tmp_path, monkeypatch
):
    monkeypatch.setenv("QC_STORAGE_ROOT", str(tmp_path))
    created = auth_client.post(
        "/api/v1/pad/create_inspection_job", json={"sku_id": seeded_sku.id}
    )
    job_id = created.json()["job_id"]
    fixture = Path(__file__).parent / "fixtures" / "qc" / "capture_red_square_pass.png"
    attached = auth_client.post(
        f"/api/v1/pad/inspection-jobs/{job_id}/media",
        data={"capture_source": "mac_usb_camera"},
        files={"image": ("mac-usb-camera.png", fixture.read_bytes(), "image/png")},
    )
    assert attached.status_code == 201

    from src.qc_model.studio import ai_gateway
    state = auth_client.get(f"/api/v1/pad/inspection-jobs/{job_id}").json()
    from src.db.sku_models import QCDetectionPoint
    configured_point = db_session.query(QCDetectionPoint).filter_by(
        id=state["checkpoints"][0]["id"]
    ).one()
    configured_point.cv_config_json = {
        "analyzers": [{"name": "pistil_localization", "params": {}}],
    }
    configured_point.expected_features_json = {}
    configured_point.regions_json = [{"x": 0.1, "y": 0.1, "w": 0.5, "h": 0.5}]
    db_session.commit()
    fake_results = [
        {
            "point_code": point["point_code"],
            "result": "not_visible",
            "confidence": 0.25,
            "observed_value": None,
            "notes": "fixture does not establish this checkpoint",
        }
        for point in state["checkpoints"]
    ]
    captured = {}

    def fake_inspect(**kwargs):
        captured.update(kwargs)
        return {
            "summary": "Operator review required.",
            "checkpoint_results": fake_results,
            "assistant": {
                "role": "vision",
                "provider": "openai_compatible",
                "model": "replaceable-vision-default",
                "elapsed_ms": 321,
                "mode": "live",
            },
        }

    monkeypatch.setattr(ai_gateway, "inspect_image", fake_inspect)
    response = auth_client.post(
        f"/api/v1/pad/inspection-jobs/{job_id}/vision-analyze"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["operator_review_required"] is True
    assert len(data["checkpoint_results"]) == len(state["checkpoints"])
    assert all(item["result"] == "not_visible" for item in data["checkpoint_results"])
    assert captured["cv_context"]["verdict_effect"] == "informational_only"
    assert captured["cv_context"]["points"][0]["point_code"] == configured_point.point_code
    assert configured_point.point_code in captured["fallback_crops"]
    crop_path = captured["fallback_crops"][configured_point.point_code][0]
    assert crop_path.is_file()
    assert crop_path.stat().st_size <= 200 * 1024
    cv_by_code = {item["point_code"]: item for item in data["cv_preanalysis"]}
    assert cv_by_code[configured_point.point_code]["cv_status"] == "completed"
    assert data["timings_ms"]["cv"] >= 0
    assert data["fallback_crops"][0]["point_code"] == configured_point.point_code
    assert data["fallback_crops"][0]["size_bytes"] <= 200 * 1024

    from src.db.execution_models import QCCheckpointResult, QCModelResult
    model_row = db_session.query(QCModelResult).filter_by(job_id=job_id).one()
    assert model_row.model_name == "replaceable-vision-default"
    assert model_row.media_id == attached.json()["media_id"]
    stored_cv = {item["point_code"]: item for item in model_row.raw_output["cv_preanalysis"]}
    assert stored_cv[configured_point.point_code]["cv_status"] == "completed"
    assert model_row.raw_output["fallback_crops"][0]["size_bytes"] <= 200 * 1024
    assert db_session.query(QCCheckpointResult).filter_by(job_id=job_id).count() == 0
    unchanged = auth_client.get(f"/api/v1/pad/inspection-jobs/{job_id}").json()
    assert unchanged["status"] == "pending"
    assert unchanged["final_report"] is None


def test_stage2_control_assets_include_camera_and_real_report():
    static_dir = Path(__file__).resolve().parent.parent / "src" / "web" / "static"
    inspection_js = (static_dir / "pad_inspection.js").read_text()
    report_js = (static_dir / "pad_report.js").read_text()

    assert "navigator.mediaDevices.getUserMedia" in inspection_js
    assert "mac_usb_camera" in inspection_js
    assert "run-vision-btn" in inspection_js
    assert "/vision-analyze" in inspection_js
    assert "/checkpoint-results" in inspection_js
    assert "/finalize" in inspection_js
    assert "/api/v1/pad/inspection-jobs/" in report_js
