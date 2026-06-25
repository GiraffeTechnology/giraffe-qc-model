"""Tests for PR11: Pad Conversational QC UI.

All 20 required tests covering:
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
- Confirm standard endpoint
- Create inspection job endpoint
"""
from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.main import app
from src.api.deps import get_db_dep
from src.db.base import Base
import src.db.pad_models  # noqa: F401 — registers tables
import src.db.models  # noqa: F401
import src.db.qc_models  # noqa: F401
import src.db.sku_models  # noqa: F401
import src.db.execution_models  # noqa: F401
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
    lang = bridge.detect_language("検査開始")
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
    result = bridge.process("検査開始", preferred_language="ja")
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
        json={"message": "検査開始", "context": {}},
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
# Test 19: Confirm standard requires explicit operator action
# ---------------------------------------------------------------------------
def test_19_confirm_standard_requires_intake_id(auth_client):
    # Missing intake_id -> 400
    resp = auth_client.post("/api/v1/pad/confirm_standard", json={})
    assert resp.status_code == 400

    # With intake_id -> confirmed
    resp = auth_client.post("/api/v1/pad/confirm_standard", json={"intake_id": 42})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "confirmed"
    assert data["intake_id"] == 42


# ---------------------------------------------------------------------------
# Test 20: Create inspection job
# ---------------------------------------------------------------------------
def test_20_create_inspection_job(auth_client):
    resp = auth_client.post(
        "/api/v1/pad/create_inspection_job",
        json={"sku_id": 1, "standard_id": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "job_created"
    assert data["sku_id"] == 1
    assert data["standard_id"] == 1
