"""SQLAlchemy models for QC standard intake pipeline."""
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow


class QCStandardIntake(Base):
    """One standard intake session — from raw operator input to confirmation."""
    __tablename__ = "qc_standard_intakes"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(
        ForeignKey("qc_sku_items.id"), nullable=False, index=True
    )
    # admin_ui | im | email | voice | api | pad | web
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    # optional: wechat | email | web | etc.
    source_channel: Mapped[Optional[str]] = mapped_column(String(64))
    source_message_id: Mapped[Optional[str]] = mapped_column(String(256))
    operator_id: Mapped[Optional[str]] = mapped_column(String(128))
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    normalized_text: Mapped[Optional[str]] = mapped_column(Text)
    # received | extracted | pending_confirmation | confirmed | rejected
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    extracted_json: Mapped[Optional[dict]] = mapped_column(JSON)
    confirmation_payload_json: Mapped[Optional[dict]] = mapped_column(JSON)
    parser_version: Mapped[Optional[str]] = mapped_column(String(64))
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    media: Mapped[list["QCIntakeMedia"]] = relationship(
        "QCIntakeMedia", back_populates="intake", cascade="all, delete-orphan"
    )
    confirmations: Mapped[list["QCOperatorConfirmation"]] = relationship(
        "QCOperatorConfirmation", back_populates="intake", cascade="all, delete-orphan"
    )


class QCIntakeMedia(Base):
    """Standard photos, voice files, PDFs, etc. uploaded during a standard intake session."""
    __tablename__ = "qc_intake_media"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    intake_id: Mapped[str] = mapped_column(
        ForeignKey("qc_standard_intakes.id"), nullable=False, index=True
    )
    # image | voice | pdf | doc | excel | video | other
    media_type: Mapped[str] = mapped_column(String(32), nullable=False, default="image")
    # standard_photo | instruction_voice | acceptance_doc | other
    media_role: Mapped[str] = mapped_column(String(64), nullable=False, default="standard_photo")
    image_url: Mapped[Optional[str]] = mapped_column(String(512))
    local_path: Mapped[Optional[str]] = mapped_column(String(512))
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(512))
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    width_px: Mapped[Optional[int]] = mapped_column(Integer)
    height_px: Mapped[Optional[int]] = mapped_column(Integer)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    intake: Mapped["QCStandardIntake"] = relationship("QCStandardIntake", back_populates="media")


class QCOperatorConfirmation(Base):
    """Operator confirmation, modification, or rejection of an extracted standard draft."""
    __tablename__ = "qc_operator_confirmations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    intake_id: Mapped[str] = mapped_column(
        ForeignKey("qc_standard_intakes.id"), nullable=False, index=True
    )
    sku_id: Mapped[str] = mapped_column(
        ForeignKey("qc_sku_items.id"), nullable=False, index=True
    )
    # confirmed | modified | rejected
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmed_by: Mapped[str] = mapped_column(String(128), nullable=False)
    confirmed_json: Mapped[Optional[dict]] = mapped_column(JSON)
    operator_comment: Mapped[Optional[str]] = mapped_column(Text)
    created_standard_revision_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("qc_sku_standard_revisions.id"), index=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    intake: Mapped["QCStandardIntake"] = relationship(
        "QCStandardIntake", back_populates="confirmations"
    )
