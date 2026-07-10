"""SQLAlchemy models for the Jetson Xavier NX inference runner (server side).

A ``QCJetsonRunner`` is the Server's record of a provisioned Jetson runner and
its current 1:1 binding to a workstation/Pad. The Jetson never writes here
itself (it never talks to the Server); the Pad reports the pairing binding and
health on sync — so these rows can lag reality and are surfaced on the Pad, the
only operator-facing window into a headless Jetson.

``QCJetsonPairingEvent`` is an append-only audit trail (provision / pair /
re-pair / unpair / health) — important for the fail-closed re-pair story.
"""
from __future__ import annotations

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
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow


class QCJetsonRunner(Base):
    """A provisioned Jetson runner and its current workstation/Pad binding."""

    __tablename__ = "qc_jetson_runners"
    __table_args__ = (
        UniqueConstraint("tenant_id", "jetson_device_id", name="uq_jetson_device_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")

    # ── Provisioning identity (created off-floor; on the chassis label) ──────
    jetson_device_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    pubkey_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_version: Mapped[Optional[str]] = mapped_column(String(64))
    provisioned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # ── Current 1:1 binding (set when the Pad reports a pairing on sync) ─────
    # unpaired | paired
    pairing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unpaired", index=True)
    # usb | wifi
    pairing_path: Mapped[Optional[str]] = mapped_column(String(16))
    workstation_pk: Mapped[Optional[str]] = mapped_column(
        ForeignKey("qc_workstations.id"), index=True
    )
    paired_pad_device_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    paired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    unpaired_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── Health (reported via the Pad; §6.1) — surfaced on the Pad UI ─────────
    readiness_state: Mapped[Optional[str]] = mapped_column(String(32))
    service_up: Mapped[Optional[bool]] = mapped_column(Boolean)
    model_loaded: Mapped[Optional[bool]] = mapped_column(Boolean)
    temperature_c: Mapped[Optional[float]] = mapped_column(Float)
    throttling: Mapped[Optional[bool]] = mapped_column(Boolean)
    disk_free_percent: Mapped[Optional[float]] = mapped_column(Float)
    last_inference_latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    health_reported_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    events: Mapped[list["QCJetsonPairingEvent"]] = relationship(
        "QCJetsonPairingEvent", back_populates="runner", cascade="all, delete-orphan"
    )


class QCJetsonPairingEvent(Base):
    """Append-only audit row for a Jetson runner's lifecycle."""

    __tablename__ = "qc_jetson_pairing_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    runner_pk: Mapped[str] = mapped_column(
        ForeignKey("qc_jetson_runners.id"), nullable=False, index=True
    )
    # provisioned | paired | repaired | unpaired | health_reported
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    pairing_path: Mapped[Optional[str]] = mapped_column(String(16))
    workstation_id: Mapped[Optional[str]] = mapped_column(String(128))
    pad_device_id: Mapped[Optional[str]] = mapped_column(String(128))
    detail_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    runner: Mapped["QCJetsonRunner"] = relationship("QCJetsonRunner", back_populates="events")
