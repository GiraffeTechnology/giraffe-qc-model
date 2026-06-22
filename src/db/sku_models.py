"""SQLAlchemy models for QC SKU catalog (sample library for Android Pad)."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow


class QCSkuItem(Base):
    """SKU / sample master entry — the operator-facing item catalog."""
    __tablename__ = "qc_sku_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    item_number: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text)
    # "active" | "inactive" | "archived"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    photos: Mapped[list["QCStandardPhoto"]] = relationship(
        "QCStandardPhoto", back_populates="sku", cascade="all, delete-orphan"
    )
    inspection_requirements: Mapped[list["QCInspectionRequirement"]] = relationship(
        "QCInspectionRequirement", back_populates="sku", cascade="all, delete-orphan"
    )
    detection_points: Mapped[list["QCDetectionPoint"]] = relationship(
        "QCDetectionPoint", back_populates="sku", cascade="all, delete-orphan"
    )


class QCStandardPhoto(Base):
    """Standard/reference photo metadata for a QC SKU."""
    __tablename__ = "qc_standard_photos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("qc_sku_items.id"), nullable=False, index=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(512))
    local_path: Mapped[Optional[str]] = mapped_column(String(512))
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(512))
    angle: Mapped[Optional[str]] = mapped_column(String(64))
    view_type: Mapped[Optional[str]] = mapped_column(String(64))
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    width_px: Mapped[Optional[int]] = mapped_column(Integer)
    height_px: Mapped[Optional[int]] = mapped_column(Integer)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sku: Mapped["QCSkuItem"] = relationship("QCSkuItem", back_populates="photos")


class QCInspectionRequirement(Base):
    """Inspection requirement / pass criteria for a QC SKU."""
    __tablename__ = "qc_inspection_requirements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("qc_sku_items.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    requirement_text: Mapped[str] = mapped_column(Text, nullable=False)
    # "minor" | "major" | "critical"
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="major")
    pass_criteria: Mapped[Optional[str]] = mapped_column(Text)
    tolerance_json: Mapped[Optional[dict]] = mapped_column(JSON)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sku: Mapped["QCSkuItem"] = relationship("QCSkuItem", back_populates="inspection_requirements")
    detection_points: Mapped[list["QCDetectionPoint"]] = relationship(
        "QCDetectionPoint", back_populates="requirement"
    )


class QCDetectionPoint(Base):
    """Detection point / QC focus area definition for a SKU."""
    __tablename__ = "qc_detection_points"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("qc_sku_items.id"), nullable=False, index=True)
    requirement_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("qc_inspection_requirements.id"), index=True
    )
    point_code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    roi_json: Mapped[Optional[dict]] = mapped_column(JSON)
    expected_value: Mapped[Optional[str]] = mapped_column(String(256))
    method_hint: Mapped[Optional[str]] = mapped_column(String(128))
    # "minor" | "major" | "critical"
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="major")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sku: Mapped["QCSkuItem"] = relationship("QCSkuItem", back_populates="detection_points")
    requirement: Mapped[Optional["QCInspectionRequirement"]] = relationship(
        "QCInspectionRequirement", back_populates="detection_points"
    )
