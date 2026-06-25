"""Core agent service: process pad messages through OpenClaw pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.db.pad_models import QCConversationMessage
from src.openclaw.qc_agent_bridge import (
    INTENT_THRESHOLD,
    QCAgentBridge,
    get_bridge,
)
from src.pad.session_service import get_or_create_conversation_session


@dataclass
class ActionCard:
    action_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False


@dataclass
class PadAgentResponse:
    reply_text: str
    detected_language: str
    normalized_text_en: str
    intent: str
    confidence: float
    action_card: Optional[ActionCard] = None
    requires_confirmation: bool = False
    linked_intake_id: Optional[int] = None
    linked_job_id: Optional[int] = None


def _build_action_card(intent: str, normalized_en: str, context: Dict[str, Any]) -> Optional[ActionCard]:
    if intent == "start_inspection":
        return ActionCard(
            action_type="start_inspection",
            payload={"sku_id": context.get("sku_id"), "standard_id": context.get("standard_id")},
            requires_confirmation=False,
        )
    if intent == "submit_checkpoint":
        return ActionCard(
            action_type="submit_checkpoint",
            payload={"raw_text": normalized_en},
            requires_confirmation=False,
        )
    if intent == "confirm_intake":
        return ActionCard(
            action_type="confirm_intake",
            payload={"intake_id": context.get("pending_intake_id")},
            requires_confirmation=False,
        )
    if intent == "view_report":
        return ActionCard(
            action_type="view_report",
            payload={"job_id": context.get("job_id")},
            requires_confirmation=False,
        )
    if intent == "set_language":
        return ActionCard(
            action_type="set_language",
            payload={"language": context.get("language")},
            requires_confirmation=False,
        )
    return None


def process_pad_message(
    db: Session,
    operator_id: int,
    tenant_id: str,
    preferred_language: str,
    raw_text: str,
    context: Optional[Dict[str, Any]] = None,
    bridge: Optional[QCAgentBridge] = None,
) -> PadAgentResponse:
    """Process operator message through multilingual pipeline and save audit trail."""
    ctx = context or {}
    b = bridge or get_bridge()

    conv_session = get_or_create_conversation_session(
        db, operator_id, tenant_id, preferred_language
    )

    ocr = b.process(raw_text, preferred_language)

    if ocr.confidence < INTENT_THRESHOLD:
        reply_text = ocr.localized_reply or "Clarification needed"
        action_card = None
        requires_confirmation = False
    else:
        action_card = _build_action_card(ocr.intent, ocr.normalized_text_en, ctx)
        requires_confirmation = action_card.requires_confirmation if action_card else False
        reply_en = ocr.intent.replace("_", " ").capitalize()
        reply_text = b.localize_response(reply_en, preferred_language)

    user_msg = QCConversationMessage(
        tenant_id=tenant_id,
        session_id=conv_session.id,
        operator_id=operator_id,
        role="user",
        source_language=ocr.detected_language,
        preferred_language=preferred_language,
        raw_text_original=raw_text,
        normalized_text_en=ocr.normalized_text_en,
        intent=ocr.intent,
        confidence_score=ocr.confidence,
        linked_intake_id=ctx.get("pending_intake_id"),
        linked_job_id=ctx.get("job_id"),
        created_at=datetime.utcnow(),
    )
    db.add(user_msg)

    assistant_msg = QCConversationMessage(
        tenant_id=tenant_id,
        session_id=conv_session.id,
        operator_id=operator_id,
        role="assistant",
        source_language="en",
        preferred_language=preferred_language,
        normalized_text_en=reply_text,
        translated_output_text=reply_text,
        action_json=json.dumps(action_card.payload if action_card else {}),
        intent=ocr.intent,
        confidence_score=ocr.confidence,
        linked_intake_id=ctx.get("pending_intake_id"),
        linked_job_id=ctx.get("job_id"),
        created_at=datetime.utcnow(),
    )
    db.add(assistant_msg)
    db.commit()

    return PadAgentResponse(
        reply_text=reply_text,
        detected_language=ocr.detected_language,
        normalized_text_en=ocr.normalized_text_en,
        intent=ocr.intent,
        confidence=ocr.confidence,
        action_card=action_card,
        requires_confirmation=requires_confirmation,
        linked_intake_id=ctx.get("pending_intake_id"),
        linked_job_id=ctx.get("job_id"),
    )
