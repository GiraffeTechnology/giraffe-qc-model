"""SQLAlchemy models for bundle management + workstation management (§6, §7).

A **bundle** is a signed, versioned package of SKUs + standard revisions +
reference photos, described by the canonical manifest in
``src.qc_model.bundle.manifest``. The publish action that *creates* a bundle
lives in the studio (S2); this session owns the recorded history plus the
download/assign lifecycle and the workstation fleet state.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow

# Workstation pairing lifecycle
PAIRED_STATUS_UNPAIRED = "unpaired"
PAIRED_STATUS_PENDING = "pending"
PAIRED_STATUS_PAIRED = "paired"

# Bundle signature/publish lifecycle
BUNDLE_STATUS_SIGNED = "signed"
BUNDLE_STATUS_PUBLISHED = "published"
BUNDLE_STATUS_REVOKED = "revoked"


class QCBundle(Base):
    """A signed bundle version recorded for history/download/assignment.

    The signed manifest bytes are stored verbatim in ``manifest_json`` alongside
    the signature envelope so downloads can be re-verified fail-closed without
    trusting any denormalized column.
    """

    __tablename__ = "qc_bundles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "bundle_version", name="uq_bundle_tenant_version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    bundle_version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # signed | published | revoked
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=BUNDLE_STATUS_SIGNED)
    sku_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    standard_revision_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))

    # Signature envelope + canonical manifest (the security surface).
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(256), nullable=False)
    signature_algo: Mapped[str] = mapped_column(String(32), nullable=False, default="hmac-sha256")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    assignments: Mapped[list["QCBundleAssignment"]] = relationship(
        "QCBundleAssignment", back_populates="bundle", cascade="all, delete-orphan"
    )


class QCWorkstation(Base):
    """A registered inspection workstation / Pad (fields per §6, exact set)."""

    __tablename__ = "qc_workstations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workstation_id", name="uq_workstation_tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")

    # §6 field set
    workstation_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    site_or_line: Mapped[Optional[str]] = mapped_column(String(256))
    paired_status: Mapped[str] = mapped_column(String(32), nullable=False, default=PAIRED_STATUS_UNPAIRED)
    assigned_bundle_version: Mapped[Optional[str]] = mapped_column(String(64))
    installed_bundle_version: Mapped[Optional[str]] = mapped_column(String(64))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[Optional[str]] = mapped_column(String(64))
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    # Pairing handshake support (token / QR placeholder).
    pairing_token: Mapped[Optional[str]] = mapped_column(String(128))
    outbox_upload_status: Mapped[Optional[str]] = mapped_column(String(64))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    assignments: Mapped[list["QCBundleAssignment"]] = relationship(
        "QCBundleAssignment", back_populates="workstation", cascade="all, delete-orphan"
    )


class QCBundleAssignment(Base):
    """Append-only record of a bundle version assigned to a workstation."""

    __tablename__ = "qc_bundle_assignments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    workstation_pk: Mapped[str] = mapped_column(
        ForeignKey("qc_workstations.id"), nullable=False, index=True
    )
    bundle_pk: Mapped[str] = mapped_column(ForeignKey("qc_bundles.id"), nullable=False, index=True)
    bundle_version: Mapped[str] = mapped_column(String(64), nullable=False)
    assigned_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    workstation: Mapped["QCWorkstation"] = relationship("QCWorkstation", back_populates="assignments")
    bundle: Mapped["QCBundle"] = relationship("QCBundle", back_populates="assignments")
