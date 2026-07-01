"""SQLAlchemy model for the PR 22 LLM rule-authoring pipeline.

A ``RuleAuthoringJob`` tracks one LLM authoring run against a PR 21 source
fragment (or an extraction job's fragments). The proposals it produces are
stored in the *existing* PR 20 ``qc_learned_detection_point_proposals`` table
(reusing that approval workflow), tagged with ``rule_authoring_job_id`` and
``source_fragment_id``.

Nothing here writes to a Training Pack table. Proposals are draft-only until a
supervisor approves them; there is no apply path in PR 22.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow


class RuleAuthoringJob(Base):
    __tablename__ = "qc_rule_authoring_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    training_pack_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Scope of the run: a single fragment and/or a whole extraction job.
    source_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    source_fragment_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    extraction_job_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    provider: Mapped[Optional[str]] = mapped_column(String(128))
    model: Mapped[Optional[str]] = mapped_column(String(128))
    proposal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
