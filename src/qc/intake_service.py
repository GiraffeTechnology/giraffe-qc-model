"""Standard intake service.

Handles raw operator messages, media assets, requirement extraction,
and confirmation payload generation. Never writes to approved standard
tables directly.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from src.db.qc_checkpoint_models import (
    QCChannelMessage, QCMediaAsset, QCStandardIntake, QCAuditEvent
)


def create_intake_from_message(
    db: Session,
    *,
    sku_id: int,
    raw_text: str,
    channel_type: str = "web",
    sender_id: Optional[str] = None,
    sender_name: Optional[str] = None,
    message_type: str = "text",
    normalized_text: Optional[str] = None,
    source_type: str = "web",
    operator_id: Optional[str] = None,
) -> QCStandardIntake:
    """Create a channel message record and a linked standard intake draft."""
    msg = QCChannelMessage(
        channel_type=channel_type,
        sender_id=sender_id,
        sender_name=sender_name,
        raw_text=raw_text,
        normalized_text=normalized_text or raw_text,
        message_type=message_type,
        received_at=datetime.now(timezone.utc),
        processing_status="received",
    )
    db.add(msg)
    db.flush()

    intake = QCStandardIntake(
        sku_id=sku_id,
        source_channel_message_id=msg.id,
        source_type=source_type,
        operator_id=operator_id,
        intake_status="draft",
        parser_version="1.0",
    )
    db.add(intake)
    db.flush()

    _audit(
        db,
        entity_type="qc_standard_intake",
        entity_id=intake.id,
        event_type="intake_created",
        actor_id=operator_id,
        event_json={"sku_id": sku_id, "channel_type": channel_type},
    )
    db.commit()
    return intake


def attach_media_to_intake(
    db: Session,
    *,
    storage_uri: str,
    media_type: str = "image",
    media_role: str = "standard_photo",
    sha256: Optional[str] = None,
    file_size: Optional[int] = None,
    uploaded_by: Optional[str] = None,
) -> QCMediaAsset:
    """Create a media asset record. Caller links it to intake or standard as needed."""
    asset = QCMediaAsset(
        media_type=media_type,
        media_role=media_role,
        storage_uri=storage_uri,
        sha256=sha256,
        file_size=file_size,
        uploaded_by=uploaded_by,
    )
    db.add(asset)
    db.commit()
    return asset


def transcribe_voice_if_needed(
    db: Session,
    message: QCChannelMessage,
    transcript: str,
) -> QCChannelMessage:
    """Store voice transcript in normalized_text without overwriting raw_text."""
    message.normalized_text = transcript
    message.message_type = "voice"
    db.commit()
    return message


def extract_requirements(
    db: Session,
    intake: QCStandardIntake,
    extracted_json: dict,
    confidence_score: float = 1.0,
) -> QCStandardIntake:
    """Store extracted draft requirements. Does NOT create an approved standard."""
    intake.extracted_json = extracted_json
    intake.confidence_score = confidence_score
    intake.intake_status = "extracted"
    db.commit()
    return intake


def generate_confirmation_payload(intake: QCStandardIntake) -> dict:
    """Build the operator-facing confirmation payload from the extracted draft."""
    if not intake.extracted_json:
        return {"error": "No extracted data available for confirmation."}
    checkpoints = intake.extracted_json.get("checkpoints", [])
    items = []
    for i, cp in enumerate(checkpoints, start=1):
        items.append({
            "index": i,
            "code": cp.get("code", f"CP_{i:03d}"),
            "name": cp.get("name"),
            "target_part": cp.get("target_part"),
            "pass_rule_text": cp.get("pass_rule_text"),
            "severity": cp.get("severity", "major"),
            "expected_values": cp.get("expected_values"),
        })
    return {
        "intake_id": intake.id,
        "status": "pending_operator_confirmation",
        "product": intake.extracted_json.get("product_name"),
        "checkpoints": items,
        "message": (
            "Please reply CONFIRM or provide corrections, "
            "e.g. 'Rhinestone count should be 8.'"
        ),
    }


def mark_intake_pending_confirmation(
    db: Session,
    intake: QCStandardIntake,
) -> QCStandardIntake:
    intake.intake_status = "pending_confirmation"
    db.commit()
    return intake


def _audit(
    db: Session,
    *,
    entity_type: str,
    entity_id: int,
    event_type: str,
    actor_id: Optional[str] = None,
    event_json: Optional[dict] = None,
) -> None:
    db.add(QCAuditEvent(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        actor_id=actor_id,
        event_json=event_json or {},
    ))
