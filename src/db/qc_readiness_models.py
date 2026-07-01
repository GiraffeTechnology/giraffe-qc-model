"""SQLAlchemy model for the Training Pack readiness waiver audit log (PR 24 §4).

A waiver is an append-only, per-item supervisor override of the ONE waivable
readiness check (unresolved questions/ambiguities). It requires a supervisor
identity and a justification, is scoped to a specific item, and is never
mutated (append-only audit trail). All other readiness checks are non-waivable.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow

# The only readiness check that supports a waiver.
WAIVABLE_CHECK_ID = "no_unresolved_questions"


class QCReadinessWaiver(Base):
    """Append-only waiver record for a single unresolved-question item."""

    __tablename__ = "qc_readiness_waivers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Always WAIVABLE_CHECK_ID for now — stored for auditability/forward-compat.
    check_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # Stable identifier of the specific waived item (e.g. "<proposal_id>::<n>").
    item_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    supervisor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
