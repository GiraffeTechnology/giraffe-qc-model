"""SQLAlchemy models for the Digital QC Studio training step (PRD §9.5-9.8).

A "training judgment" is one CV+4B pass/fail run against a labeled sample
(a real object with known ground truth: qualified or staged-unqualified),
awaiting the administrator's per-decision review. Only a *reviewed* record
counts toward the rolling training window that gates publish -- an
unreviewed model output is not a training sample.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow


class QCTrainingJudgment(Base):
    """One CV+4B training judgment against a labeled sample.

    Append-only once reviewed: ``admin_decision`` is set exactly once by
    ``src.qc_model.qualification.training.submit_training_decision`` and the
    service layer refuses a second submission on the same row (PRD §9.7
    item 3: "记录采用追加式审计，不得静默覆盖原判断").
    """
    __tablename__ = "qc_training_judgments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("qc_sku_items.id"), nullable=False, index=True)
    standard_revision_id: Mapped[str] = mapped_column(
        ForeignKey("qc_sku_standard_revisions.id"), nullable=False, index=True
    )

    sample_image_path: Mapped[Optional[str]] = mapped_column(String(512))
    # "qualified" | "unqualified" -- the a-priori known ground truth for this
    # labeled training sample.
    ground_truth_label: Mapped[str] = mapped_column(String(32), nullable=False)
    ground_truth_notes: Mapped[Optional[str]] = mapped_column(Text)

    cv_evidence_json: Mapped[Optional[dict]] = mapped_column(JSON)
    model_provider: Mapped[Optional[str]] = mapped_column(String(64))
    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    model_elapsed_ms: Mapped[Optional[int]] = mapped_column(Integer)
    # "pass" | "fail" -- the model's own aggregate judgment on this sample.
    model_overall_result: Mapped[str] = mapped_column(String(16), nullable=False)
    model_checkpoint_results_json: Mapped[Optional[list]] = mapped_column(JSON)

    # "awaiting_admin_review" | "reviewed"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="awaiting_admin_review")
    # "correct" | "incorrect" -- set exactly once, on review.
    admin_decision: Mapped[Optional[str]] = mapped_column(String(16))
    admin_id: Mapped[Optional[str]] = mapped_column(String(128))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Required when admin_decision == "incorrect":
    # {point_code, model_error, correct_conclusion, correct_facts}
    correction_json: Mapped[Optional[dict]] = mapped_column(JSON)

    # Computed at creation from ground_truth_label vs model_overall_result:
    # an unqualified sample the model called "pass". Tracked independently
    # of the admin's later correct/incorrect call so a single false pass can
    # never be averaged away by an otherwise-strong window (PRD §9.6/9.7).
    is_false_pass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )


__all__ = ["QCTrainingJudgment"]
