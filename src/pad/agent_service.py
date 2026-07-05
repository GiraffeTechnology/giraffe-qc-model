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
    OpenClawResponse,
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
    linked_intake_id: Optional[str] = None
    linked_job_id: Optional[str] = None


def _build_action_card(intent: str, normalized_en: str, context: Dict[str, Any]) -> Optional[ActionCard]:
    if intent == "start_inspection":
        return ActionCard(
            action_type="start_inspection",
            payload={"type": "start_inspection", "sku_id": context.get("sku_id"), "standard_id": context.get("standard_id")},
            requires_confirmation=False,
        )
    if intent == "submit_checkpoint":
        return ActionCard(
            action_type="submit_checkpoint",
            payload={"type": "submit_checkpoint", "raw_text": normalized_en},
            requires_confirmation=False,
        )
    if intent == "confirm_intake":
        return ActionCard(
            action_type="confirm_intake",
            payload={"type": "confirm_intake", "intake_id": context.get("pending_intake_id")},
            requires_confirmation=False,
        )
    if intent == "view_report":
        return ActionCard(
            action_type="view_report",
            payload={"type": "view_report", "job_id": context.get("job_id")},
            requires_confirmation=False,
        )
    if intent == "get_report":
        return ActionCard(
            action_type="get_report",
            payload={"type": "get_report", "job_id": context.get("job_id")},
            requires_confirmation=False,
        )
    if intent == "create_inspection_job":
        return ActionCard(
            action_type="create_inspection_job",
            payload={"type": "create_inspection_job", "sku_id": context.get("sku_id")},
            requires_confirmation=False,
        )
    if intent == "set_language":
        return ActionCard(
            action_type="set_language",
            payload={"type": "set_language", "language": context.get("language")},
            requires_confirmation=False,
        )
    if intent == "update_standard_intake":
        return ActionCard(
            action_type="update_standard_intake",
            payload={"type": "update_standard_intake", "intake_id": context.get("pending_intake_id")},
            requires_confirmation=True,
        )
    return None


def _handle_create_standard_intake(
    db: Session,
    operator_id: int,
    tenant_id: str,
    raw_text: str,
    ocr: OpenClawResponse,
    ctx: Dict[str, Any],
) -> tuple[ActionCard, str]:
    """Create a QCStandardIntake record and return a standard_confirmation action card.

    The intake is created with status=pending_confirmation but NO standard revision
    is activated — that requires explicit operator confirmation via /api/v1/pad/confirm_standard.
    """
    from src.intake.service import create_standard_intake as _create_intake

    sku_id: Optional[str] = ctx.get("sku_id")
    checkpoints: List[Dict[str, Any]] = [cp.to_dict() for cp in ocr.checkpoints]

    intake_id: Optional[str] = None

    if sku_id:
        # Create intake with original raw text preserved; store canonical English separately
        intake = _create_intake(
            db,
            sku_id=str(sku_id),
            tenant_id=tenant_id,
            raw_text=raw_text,
            source_type="pad",
            source_channel=ocr.detected_language,
            operator_id=str(operator_id),
        )
        # Populate canonical English and bridge-extracted checkpoints directly
        # (bypasses extract_standard_draft which parses only English keywords)
        intake.normalized_text = ocr.normalized_text_en
        intake.extracted_json = {
            "sku_id": str(sku_id),
            "product_category": "general",
            "standard_name": "QC Standard Draft — pad intake",
            "checkpoints": checkpoints,
            "questions_for_operator": [],
        }
        intake.confirmation_payload_json = {
            "sku_id": str(sku_id),
            "checkpoints": checkpoints,
            "questions_for_operator": [],
        }
        intake.status = "pending_confirmation"
        db.commit()
        intake_id = intake.id

    action_card = ActionCard(
        action_type="standard_confirmation",
        payload={
            "type": "standard_confirmation",
            "intake_id": intake_id,
            "source_language": ocr.detected_language,
            "canonical_english_text": ocr.normalized_text_en,
            "checkpoints": checkpoints,
            "requires_confirmation": True,
        },
        requires_confirmation=True,
    )
    return action_card, "Standard intake detected — please confirm checkpoints"


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
        reply_en = "Clarification needed"
        reply_text = ocr.localized_reply or reply_en
        action_card = None
        requires_confirmation = False
        linked_intake_id = None
    elif ocr.intent == "create_standard_intake":
        action_card, reply_en = _handle_create_standard_intake(
            db, operator_id, tenant_id, raw_text, ocr, ctx
        )
        reply_text = b.localize_response(reply_en, preferred_language)
        requires_confirmation = True
        # Extract intake_id from action card payload for audit trail
        linked_intake_id = action_card.payload.get("intake_id")
    else:
        action_card = _build_action_card(ocr.intent, ocr.normalized_text_en, ctx)
        requires_confirmation = action_card.requires_confirmation if action_card else False
        reply_en = ocr.intent.replace("_", " ").capitalize()
        reply_text = b.localize_response(reply_en, preferred_language)
        linked_intake_id = ctx.get("pending_intake_id")

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
        linked_intake_id=None,  # Integer column; intake IDs are string UUIDs
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
        normalized_text_en=reply_en,
        translated_output_text=reply_text,
        action_json=json.dumps(action_card.payload if action_card else {}),
        intent=ocr.intent,
        confidence_score=ocr.confidence,
        linked_intake_id=None,  # Integer column; intake IDs are string UUIDs
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
        linked_intake_id=linked_intake_id,
        linked_job_id=ctx.get("job_id"),
    )
