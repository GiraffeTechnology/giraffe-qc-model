"""SQLAlchemy models for Standard Probation / qualification (PRD Authoring
Extension §3).

A newly installed standard is treated like a new employee: it works *real*
production jobs under mandatory human supervision until it proves it can be
trusted solo. Progress is tracked per ``standard_revision_id`` (not per SKU):

* :class:`QCProbation` — one probation record per standard revision, holding the
  running counters and the qualification thresholds.
* :class:`QCProbationJob` — one row per real production job worked during
  probation, recording the ``(ai_verdict, human_final_verdict, agreed)`` triple
  plus any per-detection-point disagreements.

Safety invariants:
- Everything is tenant-scoped.
- Jobs are append-only evidence of real work — never a synthetic test set.
- Agreement rate is meaningless below the minimum sample size, so the gate
  refuses to qualify a standard before it is met, even at 100% agreement.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow

# Probation record status.
PROBATION_ACTIVE = "active"       # accepting jobs, human confirmation mandatory
PROBATION_PAUSED = "paused"       # admin paused to edit the standard in Studio
PROBATION_QUALIFIED = "qualified"  # gate met → standard may run solo

VALID_PROBATION_STATUS = frozenset(
    {PROBATION_ACTIVE, PROBATION_PAUSED, PROBATION_QUALIFIED}
)


class QCProbation(Base):
    """Probation state + counters for one standard revision (§3.2)."""

    __tablename__ = "qc_probations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "standard_revision_id", name="uq_probation_tenant_revision"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    sku_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    standard_revision_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # active | paused | qualified
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=PROBATION_ACTIVE)

    # Qualification gate parameters (deployment-configurable; the *concept* is
    # mandatory — Supplement §5 "Mature").
    min_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    agreement_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.90)
    recheck_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    # Running counters over recorded real jobs.
    jobs_recorded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    agreements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    qualified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paused_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    jobs: Mapped[list["QCProbationJob"]] = relationship(
        "QCProbationJob", back_populates="probation", cascade="all, delete-orphan"
    )


class QCProbationJob(Base):
    """One real production job worked while a standard was on probation (§3.2)."""

    __tablename__ = "qc_probation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "probation_id", "job_ref", name="uq_probation_job_ref"
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    probation_id: Mapped[str] = mapped_column(
        ForeignKey("qc_probations.id"), nullable=False, index=True
    )
    standard_revision_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Optional external job identifier (dedupes re-submits of the same job).
    job_ref: Mapped[Optional[str]] = mapped_column(String(128))

    ai_verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    human_final_verdict: Mapped[str] = mapped_column(String(32), nullable=False)
    agreed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Per-detection-point divergences for the disagreement report (§3.2). List
    # of {"point_code", "ai_verdict", "human_final_verdict"}.
    point_disagreements_json: Mapped[Optional[list]] = mapped_column(JSON)

    # Ordinal within the probation (1-based) so recheck cadence is auditable.
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    probation: Mapped["QCProbation"] = relationship("QCProbation", back_populates="jobs")
