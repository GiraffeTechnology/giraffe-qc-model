"""New QC data models for Giraffe QC Model Phase 1.

These models are separate from models.py to maintain backward compatibility,
but use the same Base class so they're part of the same metadata.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow


class ProductStandard(Base):
    """Product QC standard definition per SKU."""
    __tablename__ = "product_standards"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    # "draft" | "active" | "deprecated"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    photos: Mapped[list["StandardPhoto"]] = relationship("StandardPhoto", back_populates="standard")
    qc_points: Mapped[list["QCPoint"]] = relationship("QCPoint", back_populates="standard")
    inspection_runs: Mapped[list["InspectionRun"]] = relationship("InspectionRun", back_populates="standard")


class StandardPhoto(Base):
    """Reference photo for a product standard."""
    __tablename__ = "standard_photos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    standard_id: Mapped[str] = mapped_column(ForeignKey("product_standards.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(String(128), nullable=False)
    angle: Mapped[Optional[str]] = mapped_column(String(64))
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    standard: Mapped["ProductStandard"] = relationship("ProductStandard", back_populates="photos")


class QCPoint(Base):
    """A single QC inspection point/criterion for a standard."""
    __tablename__ = "qc_points"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    standard_id: Mapped[str] = mapped_column(ForeignKey("product_standards.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    qc_point_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # "visual" | "dimensional" | "label" | "color" | "custom"
    rule_type: Mapped[Optional[str]] = mapped_column(String(64))
    roi_json: Mapped[Optional[dict]] = mapped_column(JSON)
    # "critical" | "major" | "minor"
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="major")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    standard: Mapped["ProductStandard"] = relationship("ProductStandard", back_populates="qc_points")


class CapturePhoto(Base):
    """A production photo captured for QC inspection."""
    __tablename__ = "capture_photos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    # "manual" | "video_capture" | "auto"
    capture_source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")

    inspection_runs: Mapped[list["InspectionRun"]] = relationship("InspectionRun", back_populates="capture_photo")


class InspectionRun(Base):
    """An inspection run linking a capture to a standard."""
    __tablename__ = "inspection_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    standard_id: Mapped[str] = mapped_column(ForeignKey("product_standards.id"), nullable=False, index=True)
    capture_photo_id: Mapped[str] = mapped_column(ForeignKey("capture_photos.id"), nullable=False, index=True)
    # "pending" | "running" | "done" | "failed"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    # "pass" | "fail" | "review_required"
    overall_result: Mapped[Optional[str]] = mapped_column(String(32))
    engine: Mapped[Optional[str]] = mapped_column(String(64))
    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    standard: Mapped["ProductStandard"] = relationship("ProductStandard", back_populates="inspection_runs")
    capture_photo: Mapped["CapturePhoto"] = relationship("CapturePhoto", back_populates="inspection_runs")
    results: Mapped[list["InspectionResult"]] = relationship("InspectionResult", back_populates="run")
    assets: Mapped[list["QCAsset"]] = relationship("QCAsset", back_populates="inspection_run")


class InspectionResult(Base):
    """Aggregated result for an inspection run."""
    __tablename__ = "inspection_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    inspection_run_id: Mapped[str] = mapped_column(ForeignKey("inspection_runs.id"), nullable=False, unique=True, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # "pass" | "fail" | "review_required"
    overall_result: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    engine: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    raw_output: Mapped[Optional[dict]] = mapped_column(JSON)
    fallback_used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    fallback_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    run: Mapped["InspectionRun"] = relationship("InspectionRun", back_populates="results")
    item_results: Mapped[list["InspectionItemResult"]] = relationship("InspectionItemResult", back_populates="result_obj")


class InspectionItemResult(Base):
    """Per-QC-point result within an inspection."""
    __tablename__ = "inspection_item_results"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    inspection_result_id: Mapped[str] = mapped_column(ForeignKey("inspection_results.id"), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    qc_point_id: Mapped[str] = mapped_column(String(64), nullable=False)
    qc_point_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # "pass" | "fail" | "review_required"
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reason: Mapped[Optional[str]] = mapped_column(Text)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)

    result_obj: Mapped["InspectionResult"] = relationship("InspectionResult", back_populates="item_results")


class QCAsset(Base):
    """Asset registry entry for QC-related files (photos, results, etc.)."""
    __tablename__ = "qc_assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sku_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    inspection_run_id: Mapped[Optional[str]] = mapped_column(ForeignKey("inspection_runs.id"), index=True)
    # "standard_photo" | "capture_photo" | "inspection_result" | "report"
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    # Privacy requirement §4.8.2
    contains_pii: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    inspection_run: Mapped[Optional["InspectionRun"]] = relationship("InspectionRun", back_populates="assets")
    sync_jobs: Mapped[list["SyncJob"]] = relationship("SyncJob", back_populates="asset")


class SyncTarget(Base):
    """Sync destination configuration (cloud, external storage, etc.)."""
    __tablename__ = "sync_targets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # "s3" | "oss" | "azure_blob" | "local" | "custom"
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    sync_jobs: Mapped[list["SyncJob"]] = relationship("SyncJob", back_populates="target")


class SyncJob(Base):
    """A sync job for transferring an asset to a target."""
    __tablename__ = "sync_jobs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("qc_assets.id"), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("sync_targets.id"), nullable=False, index=True)
    # "pending" | "running" | "done" | "failed"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    remote_path: Mapped[Optional[str]] = mapped_column(String(512))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    asset: Mapped["QCAsset"] = relationship("QCAsset", back_populates="sync_jobs")
    target: Mapped["SyncTarget"] = relationship("SyncTarget", back_populates="sync_jobs")
