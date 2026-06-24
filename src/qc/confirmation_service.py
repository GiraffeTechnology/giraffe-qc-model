"""Operator confirmation service.

Approved standard can only be generated after operator confirmation.
The draft extracted_json is never treated as an approved standard.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from src.db.qc_checkpoint_models import (
    QCStandardIntake, QCOperatorConfirmation, QCStandardVersion,
    QCCheckPoint, QCCheckRule, QCAuditEvent
)


def confirm_standard_intake(
    db: Session,
    *,
    intake: QCStandardIntake,
    confirmed_by: Optional[str] = None,
    confirmed_json: Optional[dict] = None,
    operator_comment: Optional[str] = None,
) -> QCOperatorConfirmation:
    confirmation = QCOperatorConfirmation(
        standard_intake_id=intake.id,
        confirmed_by=confirmed_by,
        confirmation_status="confirmed",
        confirmed_json=confirmed_json if confirmed_json is not None else intake.extracted_json,
        operator_comment=operator_comment,
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(confirmation)
    intake.intake_status = "pending_confirmation"
    db.flush()
    _audit(
        db,
        entity_type="qc_operator_confirmation",
        entity_id=confirmation.id,
        event_type="intake_confirmed",
        actor_id=confirmed_by,
        event_json={"intake_id": intake.id},
    )
    db.commit()
    return confirmation


def modify_standard_intake(
    db: Session,
    *,
    intake: QCStandardIntake,
    modified_json: dict,
    confirmed_by: Optional[str] = None,
    operator_comment: Optional[str] = None,
) -> QCOperatorConfirmation:
    """Record operator modification; intake goes back to pending_confirmation."""
    confirmation = QCOperatorConfirmation(
        standard_intake_id=intake.id,
        confirmed_by=confirmed_by,
        confirmation_status="modified",
        confirmed_json=modified_json,
        operator_comment=operator_comment,
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(confirmation)
    intake.intake_status = "pending_confirmation"
    db.commit()
    return confirmation


def reject_standard_intake(
    db: Session,
    *,
    intake: QCStandardIntake,
    confirmed_by: Optional[str] = None,
    operator_comment: Optional[str] = None,
) -> QCOperatorConfirmation:
    confirmation = QCOperatorConfirmation(
        standard_intake_id=intake.id,
        confirmed_by=confirmed_by,
        confirmation_status="rejected",
        confirmed_json=None,
        operator_comment=operator_comment,
        confirmed_at=datetime.now(timezone.utc),
    )
    db.add(confirmation)
    intake.intake_status = "rejected"
    db.commit()
    return confirmation


def create_standard_version_from_confirmed_intake(
    db: Session,
    *,
    intake: QCStandardIntake,
    confirmation: QCOperatorConfirmation,
    version_no: str = "v1.0",
    standard_name: Optional[str] = None,
    approved_by: Optional[str] = None,
) -> QCStandardVersion:
    """Create an approved standard version from a confirmed intake.

    Raises ValueError if confirmation status is not 'confirmed' or 'modified'.
    """
    if confirmation.confirmation_status not in ("confirmed", "modified"):
        raise ValueError(
            f"Cannot create standard version from confirmation status "
            f"'{confirmation.confirmation_status}'. Requires 'confirmed' or 'modified'."
        )

    confirmed_data = confirmation.confirmed_json or {}
    version = QCStandardVersion(
        sku_id=intake.sku_id,
        version_no=version_no,
        standard_name=standard_name or confirmed_data.get("product_name", "QC Standard"),
        standard_status="active",
        source_intake_id=intake.id,
        approved_by=approved_by or confirmation.confirmed_by,
        approved_at=datetime.now(timezone.utc),
        effective_from=datetime.now(timezone.utc),
    )
    db.add(version)
    db.flush()

    for i, cp_data in enumerate(confirmed_data.get("checkpoints", []), start=1):
        checkpoint = QCCheckPoint(
            standard_version_id=version.id,
            checkpoint_code=cp_data.get("code", f"CP_{i:03d}"),
            checkpoint_name=cp_data.get("name", f"Checkpoint {i}"),
            target_part=cp_data.get("target_part"),
            inspection_method=cp_data.get("inspection_method", "visual_similarity"),
            severity=cp_data.get("severity", "major"),
            pass_rule_text=cp_data.get("pass_rule_text"),
            rule_json=cp_data.get("rule_json"),
            display_order=i,
        )
        db.add(checkpoint)
        db.flush()

        if cp_data.get("check_rule"):
            rule_data = cp_data["check_rule"]
            db.add(QCCheckRule(
                checkpoint_id=checkpoint.id,
                rule_type=rule_data.get("rule_type", "visual_similarity"),
                expected_value_json=rule_data.get("expected_value_json"),
                threshold_json=rule_data.get("threshold_json"),
                fail_condition_json=rule_data.get("fail_condition_json"),
            ))

    intake.intake_status = "confirmed"
    _audit(
        db,
        entity_type="qc_standard_version",
        entity_id=version.id,
        event_type="standard_version_created",
        actor_id=approved_by,
        event_json={"sku_id": intake.sku_id, "version_no": version_no},
    )
    db.commit()
    return version


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
