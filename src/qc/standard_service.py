"""Standard and SKU management service."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session

from src.db.qc_checkpoint_models import (
    QCProductSku, QCStandardVersion, QCCheckPoint, QCAuditEvent
)


def create_sku(
    db: Session,
    *,
    sku_code: str,
    product_name: str,
    category: Optional[str] = None,
    supplier_id: Optional[int] = None,
    customer_id: Optional[int] = None,
) -> QCProductSku:
    sku = QCProductSku(
        sku_code=sku_code,
        product_name=product_name,
        category=category,
        supplier_id=supplier_id,
        customer_id=customer_id,
        status="active",
    )
    db.add(sku)
    db.commit()
    return sku


def create_standard_version(
    db: Session,
    *,
    sku_id: int,
    version_no: str,
    standard_name: str,
    approved_by: Optional[str] = None,
    source_intake_id: Optional[int] = None,
) -> QCStandardVersion:
    version = QCStandardVersion(
        sku_id=sku_id,
        version_no=version_no,
        standard_name=standard_name,
        standard_status="active",
        source_intake_id=source_intake_id,
        approved_by=approved_by,
        approved_at=datetime.now(timezone.utc),
        effective_from=datetime.now(timezone.utc),
    )
    db.add(version)
    db.flush()
    _audit(
        db,
        entity_type="qc_standard_version",
        entity_id=version.id,
        event_type="standard_version_created",
        actor_id=approved_by,
        event_json={"sku_id": sku_id, "version_no": version_no},
    )
    db.commit()
    return version


def activate_standard_version(
    db: Session,
    version: QCStandardVersion,
    actor_id: Optional[str] = None,
) -> QCStandardVersion:
    version.standard_status = "active"
    version.approved_at = datetime.now(timezone.utc)
    _audit(
        db,
        entity_type="qc_standard_version",
        entity_id=version.id,
        event_type="standard_version_activated",
        actor_id=actor_id,
    )
    db.commit()
    return version


def archive_standard_version(
    db: Session,
    version: QCStandardVersion,
    actor_id: Optional[str] = None,
) -> QCStandardVersion:
    version.standard_status = "archived"
    version.effective_to = datetime.now(timezone.utc)
    _audit(
        db,
        entity_type="qc_standard_version",
        entity_id=version.id,
        event_type="standard_version_archived",
        actor_id=actor_id,
    )
    db.commit()
    return version


def list_active_checkpoints(
    db: Session,
    standard_version_id: int,
) -> list[QCCheckPoint]:
    return (
        db.query(QCCheckPoint)
        .filter_by(standard_version_id=standard_version_id)
        .order_by(QCCheckPoint.display_order)
        .all()
    )


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
