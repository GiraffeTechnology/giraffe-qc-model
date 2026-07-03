"""SQLAlchemy models for offline Standard Bundle export (Task 03).

A ``QCStandardBundle`` records one exported, signed standard bundle for a
tenant + optional line scope. ``bundle_version`` is monotonic per
(tenant_id, line_scope): each export increments it by one. The Pad rejects any
bundle whose version is not strictly greater than what it already has installed
(downgrade protection).

This is generation-3 offline-sync metadata. It is entirely separate from the
deprecated generation-2 ``sync_targets``/``sync_jobs`` tables, which this task
must not touch.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow


class QCStandardBundle(Base):
    """One exported standard bundle (history + monotonic version tracking)."""

    __tablename__ = "qc_standard_bundles"
    __table_args__ = (
        UniqueConstraint("tenant_id", "line_scope", "bundle_version",
                         name="uq_bundle_tenant_line_version"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Optional production-line scope; empty string means "whole tenant".
    line_scope: Mapped[str] = mapped_column(String(128), nullable=False, default="", index=True)
    bundle_version: Mapped[int] = mapped_column(Integer, nullable=False)
    bundle_format_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sku_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # SHA-256 of the full archive, and of the signed manifest, for audit.
    archive_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_b64: Mapped[str] = mapped_column(Text, nullable=False)
    signing_key_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # Relative filename of the archive under the bundle store.
    archive_filename: Mapped[str] = mapped_column(String(256), nullable=False)
    generated_by: Mapped[Optional[str]] = mapped_column(String(128))
    # Last principal that downloaded the bundle (sync-window audit).
    downloaded_by: Mapped[Optional[str]] = mapped_column(String(128))
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
