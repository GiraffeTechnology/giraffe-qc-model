"""SQLAlchemy models for server verdict recomputation + results (§9).

Stores what the Pad submitted, the server-recomputed verdict, and any human
final decision — so the admin Results page can show all three side by side.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow


class QCPadSubmission(Base):
    """A verdict submission received from a Pad for a completed inspection job."""

    __tablename__ = "qc_pad_submissions"
    __table_args__ = (UniqueConstraint("tenant_id", "job_ref", name="uq_pad_submission_tenant_job"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    job_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    standard_revision_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    bundle_version: Mapped[Optional[str]] = mapped_column(String(64))
    workstation_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    # What the Pad claims — recorded but NEVER trusted for the verdict.
    pad_overall_result: Mapped[str] = mapped_column(String(32), nullable=False)
    raw_json: Mapped[Optional[dict]] = mapped_column(JSON)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    checkpoints: Mapped[list["QCSubmittedCheckpoint"]] = relationship(
        "QCSubmittedCheckpoint", back_populates="submission", cascade="all, delete-orphan"
    )
    verdict: Mapped[Optional["QCServerVerdict"]] = relationship(
        "QCServerVerdict", back_populates="submission", uselist=False, cascade="all, delete-orphan"
    )


class QCSubmittedCheckpoint(Base):
    """One Pad-submitted checkpoint result attached to a submission."""

    __tablename__ = "qc_submitted_checkpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("qc_pad_submissions.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    checkpoint_id: Mapped[str] = mapped_column(String(128), nullable=False)
    result: Mapped[str] = mapped_column(String(32), nullable=False)

    submission: Mapped["QCPadSubmission"] = relationship("QCPadSubmission", back_populates="checkpoints")


class QCServerVerdict(Base):
    """The authoritative, server-recomputed verdict for a submission."""

    __tablename__ = "qc_server_verdicts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    submission_id: Mapped[str] = mapped_column(
        ForeignKey("qc_pad_submissions.id"), nullable=False, unique=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # pass | fail | review_required
    server_overall_result: Mapped[str] = mapped_column(String(32), nullable=False)
    pad_overall_result: Mapped[str] = mapped_column(String(32), nullable=False)
    agrees: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rule_applied: Mapped[str] = mapped_column(String(64), nullable=False)

    # The revision / bundle the Pad actually used (evaluated against, not latest).
    standard_revision_id: Mapped[str] = mapped_column(String(64), nullable=False)
    bundle_version: Mapped[Optional[str]] = mapped_column(String(64))

    missing_checkpoints_json: Mapped[Optional[list]] = mapped_column(JSON)
    failing_checkpoints_json: Mapped[Optional[list]] = mapped_column(JSON)
    warnings_json: Mapped[Optional[list]] = mapped_column(JSON)
    differences_json: Mapped[Optional[list]] = mapped_column(JSON)

    # Human final decision (optional, applied later on the Results page).
    human_final_decision: Mapped[Optional[str]] = mapped_column(String(32))
    human_decided_by: Mapped[Optional[str]] = mapped_column(String(128))
    human_decision_comment: Mapped[Optional[str]] = mapped_column(Text)
    human_decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    recomputed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    submission: Mapped["QCPadSubmission"] = relationship("QCPadSubmission", back_populates="verdict")
