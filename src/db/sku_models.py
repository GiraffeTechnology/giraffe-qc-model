"""SQLAlchemy models for QC SKU catalog (shared by Pad and Server editions)."""
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow

# PRD SKU lifecycle states, exposed by the Studio status filter (WS2) and the
# Pad Administrator module (WS3). The column is a free String(32): rows written
# before this lifecycle landed may still carry the legacy values
# "active" | "inactive" | "archived"; migrating those values belongs to the
# lifecycle business-logic work, not the UI enum swap.
SKU_LIFECYCLE_STATES = (
    "draft",
    "needs_information",
    "ready_for_review",
    "confirmed",
    "published",
    "installed",
    "needs_requalification",
)


class QCSkuItem(Base):
    """SKU / sample master entry — the operator-facing item catalog."""
    __tablename__ = "qc_sku_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "item_number", name="uq_sku_tenant_item_number"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    item_number: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(128))
    description: Mapped[Optional[str]] = mapped_column(Text)
    # One of SKU_LIFECYCLE_STATES (legacy rows: "active" | "inactive" | "archived")
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
    standard_revisions: Mapped[list["QCSkuStandardRevision"]] = relationship(
        "QCSkuStandardRevision", back_populates="sku", cascade="all, delete-orphan",
        order_by="QCSkuStandardRevision.revision_no",
    )


class QCSkuStandardRevision(Base):
    """One revision of the QC inspection standard for a SKU.

    A SKU has exactly one active revision at any time.  All inspection jobs
    for that SKU pick up the active revision automatically; the operator only
    needs to confirm the standard once.  When the operator explicitly requests
    a change a new revision is created (draft/pending_confirmation) and the
    prior active revision is archived.
    """
    __tablename__ = "qc_sku_standard_revisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("qc_sku_items.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # draft | pending_confirmation | active | archived
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    # admin_ui | im | email | voice | api
    created_from: Mapped[str] = mapped_column(String(32), nullable=False, default="admin_ui")
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(128))
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_by_operator: Mapped[Optional[str]] = mapped_column(String(128))
    last_update_reason: Mapped[Optional[str]] = mapped_column(Text)
    superseded_by_revision: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sku: Mapped["QCSkuItem"] = relationship("QCSkuItem", back_populates="standard_revisions")
    photos: Mapped[list["QCStandardPhoto"]] = relationship(
        "QCStandardPhoto", back_populates="standard_revision", foreign_keys="QCStandardPhoto.standard_revision_id"
    )
    inspection_requirements: Mapped[list["QCInspectionRequirement"]] = relationship(
        "QCInspectionRequirement", back_populates="standard_revision",
        foreign_keys="QCInspectionRequirement.standard_revision_id",
    )
    detection_points: Mapped[list["QCDetectionPoint"]] = relationship(
        "QCDetectionPoint", back_populates="standard_revision",
        foreign_keys="QCDetectionPoint.standard_revision_id",
    )


class QCStandardPhoto(Base):
    """Standard/reference photo metadata for a QC SKU."""
    __tablename__ = "qc_standard_photos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("qc_sku_items.id"), nullable=False, index=True)
    standard_revision_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("qc_sku_standard_revisions.id"), index=True
    )
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
    standard_revision: Mapped[Optional["QCSkuStandardRevision"]] = relationship(
        "QCSkuStandardRevision", back_populates="photos", foreign_keys=[standard_revision_id]
    )


class QCInspectionRequirement(Base):
    """Inspection requirement / pass criteria for a QC SKU."""
    __tablename__ = "qc_inspection_requirements"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("qc_sku_items.id"), nullable=False, index=True)
    standard_revision_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("qc_sku_standard_revisions.id"), index=True
    )
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
    standard_revision: Mapped[Optional["QCSkuStandardRevision"]] = relationship(
        "QCSkuStandardRevision", back_populates="inspection_requirements",
        foreign_keys=[standard_revision_id],
    )
    detection_points: Mapped[list["QCDetectionPoint"]] = relationship(
        "QCDetectionPoint", back_populates="requirement"
    )


class QCDetectionPoint(Base):
    """Detection point / QC focus area definition for a SKU."""
    __tablename__ = "qc_detection_points"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(ForeignKey("qc_sku_items.id"), nullable=False, index=True)
    standard_revision_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("qc_sku_standard_revisions.id"), index=True
    )
    requirement_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("qc_inspection_requirements.id"), index=True
    )
    point_code: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    roi_json: Mapped[Optional[dict]] = mapped_column(JSON)
    # Spatial grounding on the SKU's standard photos (PRD Authoring Extension
    # §2). A JSON list of normalized bounding boxes
    # ``[{"image_id", "x", "y", "w", "h"}]`` (0–1 coords, top-left origin). A
    # point supports zero, one, or many regions; empty/None is valid.
    regions_json: Mapped[Optional[list]] = mapped_column(JSON)
    expected_value: Mapped[Optional[str]] = mapped_column(String(256))
    method_hint: Mapped[Optional[str]] = mapped_column(String(128))
    # Human-readable pass/fail criterion for this detection point.  Carried
    # through Admin Studio confirmation so a checkpoint keeps all three
    # semantic fields (method_hint / expected_value / pass_criteria).
    pass_criteria: Mapped[Optional[str]] = mapped_column(Text)
    # "minor" | "major" | "critical"
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="major")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sku: Mapped["QCSkuItem"] = relationship("QCSkuItem", back_populates="detection_points")
    standard_revision: Mapped[Optional["QCSkuStandardRevision"]] = relationship(
        "QCSkuStandardRevision", back_populates="detection_points", foreign_keys=[standard_revision_id]
    )
    requirement: Mapped[Optional["QCInspectionRequirement"]] = relationship(
        "QCInspectionRequirement", back_populates="detection_points"
    )

