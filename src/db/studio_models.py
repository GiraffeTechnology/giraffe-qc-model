"""SQLAlchemy models for the Admin Studio (chat-first SKU + standard training).

The Admin Studio itself reuses the existing SKU, standard-revision, detection
point and intake tables.  The only Studio-owned persistence is the signed L2
publish bundle history — one append-only row per ``Publish to Pad`` action.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from src.db.models import Base, _utcnow


class QCPublishBundle(Base):
    """One signed L2 bundle produced by the Admin Studio ``Publish to Pad`` action.

    Append-only: a bundle row is never mutated after creation.  ``manifest_json``
    holds the full bundle manifest (SKU, active revision, detection points with
    all semantic fields, standard photos); ``bundle_hash`` is the SHA-256 of the
    canonical manifest and ``signature`` is the HMAC signature over that hash.
    """
    __tablename__ = "qc_publish_bundles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    standard_revision_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # L2 = production_assisted bundle target level.
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="L2")
    manifest_version: Mapped[str] = mapped_column(String(32), nullable=False, default="studio-bundle-v1")
    manifest_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    bundle_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    signature_algorithm: Mapped[str] = mapped_column(String(32), nullable=False, default="HMAC-SHA256")
    signing_key_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default")
    detection_point_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
