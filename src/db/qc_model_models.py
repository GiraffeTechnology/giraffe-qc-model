"""SQLAlchemy models for the Phase 1 visual QC training engine.

Phase 1 persists the *checkpoint category confirmation* workflow that overlays
the existing ``qc_detection_points`` catalog. Each existing detection point can
have one classification row recording the proposed category (deterministically
suggested) and, once a QC supervisor confirms it, the confirmed category.

A detection point whose classification is unconfirmed cannot drive active
production inspection (enforced in :mod:`src.qc_model`).
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow


class QCCheckpointClassification(Base):
    """Proposed + confirmed checkpoint category for one detection point."""

    __tablename__ = "qc_checkpoint_classifications"
    __table_args__ = (
        UniqueConstraint("detection_point_id", name="uq_checkpoint_classification_dp"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    sku_id: Mapped[str] = mapped_column(
        ForeignKey("qc_sku_items.id"), nullable=False, index=True
    )
    detection_point_id: Mapped[str] = mapped_column(
        ForeignKey("qc_detection_points.id"), nullable=False, index=True
    )
    # visual_defect | physical_measurement | rule_verification | subjective_judgment
    proposed_checkpoint_category: Mapped[str] = mapped_column(String(48), nullable=False)
    confirmed_checkpoint_category: Mapped[Optional[str]] = mapped_column(String(48))
    category_confirmed_by: Mapped[Optional[str]] = mapped_column(String(128))
    category_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    classification_rationale: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def is_confirmed(self) -> bool:
        return (
            self.confirmed_checkpoint_category is not None
            and self.category_confirmed_by is not None
        )
