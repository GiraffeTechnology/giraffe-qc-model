"""SQLAlchemy models for the hot-pluggable Edge CV subsystem.

These tables back the optional Edge CV co-processor feature: physical or logical
edge devices (e.g. a Jetson Nano 2GB, a CPU fallback runner, or a mock runner),
their runtime sessions and health metrics, CV models, and the CV job lifecycle
with its audit events, structured results and evidence assets.

Design invariants (see docs/edge-cv-architecture.md):

* The service layer is the single source of truth — an edge device never writes
  to the DB directly, only through validated service APIs.
* Every device and job is hot-plug tolerant: state is driven by heartbeat TTL
  and job-lease expiration, never by an assumption that a device is reachable.
* CV results are *evidence*, not a final QC judgement — ``pass_fail_hint`` is a
  hint only.

The tables are tenant-scoped (``tenant_id``) to match the rest of the repo.
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


class EdgeCVDevice(Base):
    """A physical or logical edge CV device.

    Identity is stable across reconnects: a device keeps the same ``id`` and
    ``device_name`` but is issued a fresh session on every registration.
    """

    __tablename__ = "edge_cv_devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "device_name", name="uq_edge_cv_device_name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    device_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    # jetson_nano_2gb | cpu_runner | mock_runner | jetson_orin_nano | ...
    device_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    serial_number: Mapped[Optional[str]] = mapped_column(String(256))
    mac_address: Mapped[Optional[str]] = mapped_column(String(64))
    ip_address: Mapped[Optional[str]] = mapped_column(String(64))
    agent_version: Mapped[Optional[str]] = mapped_column(String(64))
    # unknown | registering | online | busy | degraded | offline | error | maintenance
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown", index=True)
    capabilities_json: Mapped[Optional[list]] = mapped_column(JSON)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    current_active_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    sessions: Mapped[list["EdgeCVDeviceSession"]] = relationship(
        "EdgeCVDeviceSession", back_populates="device", cascade="all, delete-orphan"
    )


class EdgeCVDeviceSession(Base):
    """A runtime session for a device. Every registration mints a new session.

    A job lease is bound to a ``session_id``; a lease from an old session is
    treated as stale after a reconnect so partial results from a previous life
    of the device can never corrupt current state.
    """

    __tablename__ = "edge_cv_device_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    device_id: Mapped[str] = mapped_column(
        ForeignKey("edge_cv_devices.id"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # active | ended
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    disconnect_reason: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    device: Mapped["EdgeCVDevice"] = relationship("EdgeCVDevice", back_populates="sessions")


class EdgeCVModel(Base):
    """Metadata for a CV model that an edge device can run."""

    __tablename__ = "edge_cv_models"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    model_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False, default="0.1.0")
    # image_preprocess | object_detection | defect_candidate_detection | ...
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # onnx | tensorrt_engine | torchscript | opencv_dnn | python_callable | mock
    model_format: Mapped[str] = mapped_column(String(32), nullable=False, default="mock")
    artifact_uri: Mapped[Optional[str]] = mapped_column(String(512))
    input_width: Mapped[Optional[int]] = mapped_column(Integer)
    input_height: Mapped[Optional[int]] = mapped_column(Integer)
    precision: Mapped[Optional[str]] = mapped_column(String(32))
    # a concrete device_type, or "any"
    target_device_type: Mapped[str] = mapped_column(String(64), nullable=False, default="any")
    required_capabilities_json: Mapped[Optional[list]] = mapped_column(JSON)
    min_memory_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    model_hash: Mapped[Optional[str]] = mapped_column(String(128))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CVJob(Base):
    """A single CV job and its lease/lifecycle state."""

    __tablename__ = "cv_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    source_asset_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    inspection_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    requested_by: Mapped[Optional[str]] = mapped_column(String(128))
    task_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # low | normal | high
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal", index=True)
    # pending | queued | leased | running | uploading_result | completed |
    # failed | retry_scheduled | cancelled | manual_review_required
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    assigned_device_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    assigned_session_id: Mapped[Optional[str]] = mapped_column(String(64))
    model_id: Mapped[Optional[str]] = mapped_column(String(64))
    input_payload_json: Mapped[Optional[dict]] = mapped_column(JSON)
    lease_owner_device_id: Mapped[Optional[str]] = mapped_column(String(64))
    lease_owner_session_id: Mapped[Optional[str]] = mapped_column(String(64))
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    queued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    leased_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    events: Mapped[list["CVJobEvent"]] = relationship(
        "CVJobEvent", back_populates="job", cascade="all, delete-orphan"
    )
    results: Mapped[list["CVResult"]] = relationship(
        "CVResult", back_populates="job", cascade="all, delete-orphan"
    )


class CVJobEvent(Base):
    """Audit log row: one row per job state transition (or notable event)."""

    __tablename__ = "cv_job_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cv_job_id: Mapped[str] = mapped_column(
        ForeignKey("cv_jobs.id"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    from_status: Mapped[Optional[str]] = mapped_column(String(32))
    to_status: Mapped[Optional[str]] = mapped_column(String(32))
    # state_transition | lease_expired | heartbeat | error | fallback | ...
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_payload_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    job: Mapped["CVJob"] = relationship("CVJob", back_populates="events")


class CVResult(Base):
    """A structured CV result for a job.

    Idempotency: one result per (job, device, session). A duplicate upload from
    the same device/session for the same job returns the existing row.
    """

    __tablename__ = "cv_results"
    __table_args__ = (
        UniqueConstraint(
            "cv_job_id",
            "device_id",
            "session_id",
            name="uq_cv_result_job_device_session",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    cv_job_id: Mapped[str] = mapped_column(
        ForeignKey("cv_jobs.id"), nullable=False, index=True
    )
    device_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64))
    model_id: Mapped[Optional[str]] = mapped_column(String(64))
    # detection | classification | measurement | preprocess | fallback | ...
    result_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # pass | fail | unknown | needs_human_review  (a hint only — NOT a verdict)
    pass_fail_hint: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    detections_json: Mapped[Optional[list]] = mapped_column(JSON)
    measurements_json: Mapped[Optional[dict]] = mapped_column(JSON)
    features_json: Mapped[Optional[dict]] = mapped_column(JSON)
    raw_output_json: Mapped[Optional[dict]] = mapped_column(JSON)
    result_hash: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    job: Mapped["CVJob"] = relationship("CVJob", back_populates="results")
    assets: Mapped[list["CVResultAsset"]] = relationship(
        "CVResultAsset", back_populates="result", cascade="all, delete-orphan"
    )


class CVResultAsset(Base):
    """An evidence asset (annotated image, crop, mask, …) for a CV result."""

    __tablename__ = "cv_result_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    cv_result_id: Mapped[str] = mapped_column(
        ForeignKey("cv_results.id"), nullable=False, index=True
    )
    # input_thumbnail | annotated_image | crop | mask | heatmap | debug_image
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    asset_hash: Mapped[Optional[str]] = mapped_column(String(128))
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    result: Mapped["CVResult"] = relationship("CVResult", back_populates="assets")


class CVCapturedPhoto(Base):
    """A still frame captured by an edge device's live auto-lock pipeline.

    (Live-Capture Auto-Lock addendum.) Distinct from ``cv_result_assets`` (which
    holds CV-*generated* evidence) and from ``cv_jobs`` (which has no room for
    GPS / user / capture provenance). The device watches a live feed, locks onto
    a candidate item, captures a frame — and *that* frame becomes the source
    asset of an auto-created ``cv_job`` (``linked_cv_job_id``).

    The photo/metadata is always persisted even if downstream job creation
    fails, so a capture is never lost; a retry sweep can re-dispatch it.
    """

    __tablename__ = "cv_captured_photos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64))
    # From the Pad/session bound to the device at capture time — passed
    # explicitly on upload, since a device may be shared across shifts.
    captured_by_user_id: Mapped[Optional[str]] = mapped_column(String(128), index=True)
    # live_auto_lock (future: manual_capture)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="live_auto_lock")
    candidate_confidence: Mapped[Optional[float]] = mapped_column(Float)
    # Canonical, full ISO 8601 with timezone.
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # Derived display/filename label mmdd_hhmmss — NOT canonical (collides across years).
    capture_time_label: Mapped[Optional[str]] = mapped_column(String(32))
    gps_lat: Mapped[Optional[float]] = mapped_column(Float)
    gps_lon: Mapped[Optional[float]] = mapped_column(Float)
    gps_accuracy_m: Mapped[Optional[float]] = mapped_column(Float)
    image_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    image_hash: Mapped[Optional[str]] = mapped_column(String(128))
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    linked_cv_job_id: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    # pending | dispatched | failed
    qc_model_dispatch_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class EdgeCVDeviceMetric(Base):
    """A point-in-time device health metric sample (from a heartbeat)."""

    __tablename__ = "edge_cv_device_metrics"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True, default="default")
    device_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64))
    cpu_usage_percent: Mapped[Optional[float]] = mapped_column(Float)
    gpu_usage_percent: Mapped[Optional[float]] = mapped_column(Float)
    memory_used_mb: Mapped[Optional[float]] = mapped_column(Float)
    memory_total_mb: Mapped[Optional[float]] = mapped_column(Float)
    temperature_celsius: Mapped[Optional[float]] = mapped_column(Float)
    power_mode: Mapped[Optional[str]] = mapped_column(String(32))
    disk_used_percent: Mapped[Optional[float]] = mapped_column(Float)
    active_job_count: Mapped[Optional[int]] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False, index=True)
