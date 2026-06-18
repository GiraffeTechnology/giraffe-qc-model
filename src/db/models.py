"""SQLAlchemy 2.x ORM models — completely independent of giraffe-agent/abcdYi."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class SampleItem(Base):
    """Standard-photo sample library entry."""
    __tablename__ = "sample_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    product_name: Mapped[Optional[str]] = mapped_column(String(256))
    image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    qc_tasks: Mapped[list["QCTask"]] = relationship("QCTask", back_populates="sample")


class QCTask(Base):
    """A single QC inspection task (one production image vs. a sample)."""
    __tablename__ = "qc_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sample_id: Mapped[int] = mapped_column(ForeignKey("sample_items.id"), nullable=False)
    source_image_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # "manual" | "video_capture"
    source_type: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    # "pending" | "running" | "done" | "failed"
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    sample: Mapped["SampleItem"] = relationship("SampleItem", back_populates="qc_tasks")
    result: Mapped[Optional["QCResult"]] = relationship("QCResult", back_populates="task", uselist=False)
    capture: Mapped[Optional["CaptureRecord"]] = relationship("CaptureRecord", back_populates="qc_task", uselist=False)


class QCResult(Base):
    """Structured result from LLM comparison stored after each QC task."""
    __tablename__ = "qc_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("qc_tasks.id"), nullable=False, unique=True)
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    http_status: Mapped[int] = mapped_column(Integer, nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    # "pass" | "needs_fix" | "reject" | "unknown"
    overall_result: Mapped[str] = mapped_column(String(32), nullable=False)
    similarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    severity: Mapped[Optional[str]] = mapped_column(String(32))
    feedback_zh: Mapped[Optional[str]] = mapped_column(Text)
    feedback_en: Mapped[Optional[str]] = mapped_column(Text)
    deviations: Mapped[Optional[list]] = mapped_column(JSON)
    llm_raw_summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    task: Mapped["QCTask"] = relationship("QCTask", back_populates="result")


class VideoTask(Base):
    """A video file processing task (tier-1/2/3 pipeline tracking)."""
    __tablename__ = "video_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sku_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    # "pending" | "running" | "done" | "partial_failed" | "failed"
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Pipeline statistics (populated on completion)
    total_frames: Mapped[int] = mapped_column(Integer, default=0)
    tier1_filtered: Mapped[int] = mapped_column(Integer, default=0)
    tier2_processed: Mapped[int] = mapped_column(Integer, default=0)
    tier2_passed: Mapped[int] = mapped_column(Integer, default=0)
    tier3_llm_called: Mapped[int] = mapped_column(Integer, default=0)   # DB column kept for compat
    llm_save_ratio: Mapped[float] = mapped_column(Float, default=0.0)   # DB column kept for compat

    captures: Mapped[list["CaptureRecord"]] = relationship("CaptureRecord", back_populates="video_task")

    # ── Python-level aliases with clearer names ──────────────────────────────
    @property
    def tier3_comparator_called(self) -> int:
        return self.tier3_llm_called

    @property
    def tier3_save_ratio(self) -> float:
        return self.llm_save_ratio


class CaptureRecord(Base):
    """A frame auto-captured from video and sent to QC pipeline."""
    __tablename__ = "capture_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    video_task_id: Mapped[int] = mapped_column(ForeignKey("video_tasks.id"), nullable=False)
    frame_index: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_timestamp_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_path: Mapped[str] = mapped_column(String(512), nullable=False)
    tier2_score: Mapped[float] = mapped_column(Float, nullable=False)   # ORB match score
    qc_task_id: Mapped[Optional[int]] = mapped_column(ForeignKey("qc_tasks.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    video_task: Mapped["VideoTask"] = relationship("VideoTask", back_populates="captures")
    qc_task: Mapped[Optional["QCTask"]] = relationship("QCTask", back_populates="capture")
