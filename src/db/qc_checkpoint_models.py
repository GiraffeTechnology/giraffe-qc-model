"""QC checkpoint-driven inspection system ORM models.

All 18 tables for the checkpoint-driven workflow as per PRD_QC_DB.
Separate from existing models to maintain backward compatibility.
"""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, String, Text, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.models import Base, _utcnow


class QCProductSku(Base):
    """Product / SKU master."""
    __tablename__ = "qc_product_sku"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_code: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    product_name: Mapped[str] = mapped_column(String(256), nullable=False)
    category: Mapped[Optional[str]] = mapped_column(String(128))
    supplier_id: Mapped[Optional[int]] = mapped_column(Integer)
    customer_id: Mapped[Optional[int]] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    standard_versions: Mapped[list["QCStandardVersion"]] = relationship("QCStandardVersion", back_populates="sku")
    standard_intakes: Mapped[list["QCStandardIntake"]] = relationship("QCStandardIntake", back_populates="sku")
    inspection_jobs: Mapped[list["QCInspectionJob"]] = relationship("QCInspectionJob", back_populates="sku")


class QCChannelMessage(Base):
    """Raw operator messages from IM / WeChat / Email / Pad / Web."""
    __tablename__ = "qc_channel_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # wechat / whatsapp / email / web / pad / other
    channel_type: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_message_id: Mapped[Optional[str]] = mapped_column(String(256), index=True)
    sender_id: Mapped[Optional[str]] = mapped_column(String(128))
    sender_name: Mapped[Optional[str]] = mapped_column(String(256))
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    normalized_text: Mapped[Optional[str]] = mapped_column(Text)
    # text / voice / image / file / mixed
    message_type: Mapped[str] = mapped_column(String(32), nullable=False, default="text")
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # received / parsed / pending_confirmation / confirmed / rejected
    processing_status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    standard_intakes: Mapped[list["QCStandardIntake"]] = relationship(
        "QCStandardIntake", back_populates="source_channel_message"
    )


class QCMediaAsset(Base):
    """Reference photos, inspection photos, voice files, documents, email attachments."""
    __tablename__ = "qc_media_asset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # image / voice / video / pdf / excel / doc / zip / other
    media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    # standard_photo / inspection_photo / voice_instruction / acceptance_standard_doc / evidence_crop / annotated_result
    media_role: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    thumbnail_uri: Mapped[Optional[str]] = mapped_column(String(512))
    sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer)
    mime_type: Mapped[Optional[str]] = mapped_column(String(128))
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    exif_json: Mapped[Optional[dict]] = mapped_column(JSON)
    capture_device: Mapped[Optional[str]] = mapped_column(String(256))
    color_temperature: Mapped[Optional[str]] = mapped_column(String(64))
    lens_correction_applied: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_by: Mapped[Optional[str]] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    standard_media: Mapped[list["QCStandardMedia"]] = relationship("QCStandardMedia", back_populates="media_asset")
    inspection_media: Mapped[list["QCInspectionMedia"]] = relationship("QCInspectionMedia", back_populates="media_asset")


class QCStandardIntake(Base):
    """One standard intake session before operator approval."""
    __tablename__ = "qc_standard_intake"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("qc_product_sku.id"), nullable=False, index=True)
    source_channel_message_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qc_channel_message.id"), index=True
    )
    # im / email / pad / web
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="web")
    operator_id: Mapped[Optional[str]] = mapped_column(String(128))
    # draft / extracted / pending_confirmation / confirmed / rejected
    intake_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    parser_version: Mapped[Optional[str]] = mapped_column(String(32))
    extracted_json: Mapped[Optional[dict]] = mapped_column(JSON)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    sku: Mapped["QCProductSku"] = relationship("QCProductSku", back_populates="standard_intakes")
    source_channel_message: Mapped[Optional["QCChannelMessage"]] = relationship(
        "QCChannelMessage", back_populates="standard_intakes"
    )
    confirmations: Mapped[list["QCOperatorConfirmation"]] = relationship(
        "QCOperatorConfirmation", back_populates="standard_intake"
    )
    standard_versions: Mapped[list["QCStandardVersion"]] = relationship(
        "QCStandardVersion", back_populates="source_intake"
    )


class QCOperatorConfirmation(Base):
    """Operator confirmation or correction record."""
    __tablename__ = "qc_operator_confirmation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    standard_intake_id: Mapped[int] = mapped_column(
        ForeignKey("qc_standard_intake.id"), nullable=False, index=True
    )
    confirmation_message_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qc_channel_message.id"), index=True
    )
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(128))
    # confirmed / modified / rejected
    confirmation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    confirmed_json: Mapped[Optional[dict]] = mapped_column(JSON)
    operator_comment: Mapped[Optional[str]] = mapped_column(Text)
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    standard_intake: Mapped["QCStandardIntake"] = relationship(
        "QCStandardIntake", back_populates="confirmations"
    )


class QCStandardVersion(Base):
    """Approved QC standard version."""
    __tablename__ = "qc_standard_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("qc_product_sku.id"), nullable=False, index=True)
    version_no: Mapped[str] = mapped_column(String(32), nullable=False)
    standard_name: Mapped[str] = mapped_column(String(256), nullable=False)
    # active / inactive / archived
    standard_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    source_intake_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qc_standard_intake.id"), index=True
    )
    approved_by: Mapped[Optional[str]] = mapped_column(String(128))
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    sku: Mapped["QCProductSku"] = relationship("QCProductSku", back_populates="standard_versions")
    source_intake: Mapped[Optional["QCStandardIntake"]] = relationship(
        "QCStandardIntake", back_populates="standard_versions"
    )
    standard_media: Mapped[list["QCStandardMedia"]] = relationship(
        "QCStandardMedia", back_populates="standard_version"
    )
    checkpoints: Mapped[list["QCCheckPoint"]] = relationship(
        "QCCheckPoint", back_populates="standard_version"
    )
    inspection_jobs: Mapped[list["QCInspectionJob"]] = relationship(
        "QCInspectionJob", back_populates="standard_version"
    )


class QCStandardMedia(Base):
    """Bind reference media to an approved standard version."""
    __tablename__ = "qc_standard_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    standard_version_id: Mapped[int] = mapped_column(
        ForeignKey("qc_standard_version.id"), nullable=False, index=True
    )
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("qc_media_asset.id"), nullable=False, index=True
    )
    # front / side / back / detail_center / detail_petal / detail_back / other
    view_type: Mapped[str] = mapped_column(String(64), nullable=False, default="front")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    standard_version: Mapped["QCStandardVersion"] = relationship(
        "QCStandardVersion", back_populates="standard_media"
    )
    media_asset: Mapped["QCMediaAsset"] = relationship(
        "QCMediaAsset", back_populates="standard_media"
    )


class QCCheckPoint(Base):
    """Approved inspection checkpoint."""
    __tablename__ = "qc_check_point"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    standard_version_id: Mapped[int] = mapped_column(
        ForeignKey("qc_standard_version.id"), nullable=False, index=True
    )
    checkpoint_code: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_name: Mapped[str] = mapped_column(String(256), nullable=False)
    target_part: Mapped[Optional[str]] = mapped_column(String(256))
    # alignment / counting / defect_detection / similarity_compare / color_check / anomaly_detection
    inspection_method: Mapped[str] = mapped_column(String(64), nullable=False)
    # info / minor / major / critical
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="major")
    pass_rule_text: Mapped[Optional[str]] = mapped_column(Text)
    rule_json: Mapped[Optional[dict]] = mapped_column(JSON)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    standard_version: Mapped["QCStandardVersion"] = relationship(
        "QCStandardVersion", back_populates="checkpoints"
    )
    check_rules: Mapped[list["QCCheckRule"]] = relationship(
        "QCCheckRule", back_populates="checkpoint"
    )
    checkpoint_results: Mapped[list["QCCheckpointResult"]] = relationship(
        "QCCheckpointResult", back_populates="checkpoint"
    )
    training_samples: Mapped[list["QCTrainingSample"]] = relationship(
        "QCTrainingSample", back_populates="checkpoint"
    )


class QCCheckRule(Base):
    """Executable rule for a checkpoint."""
    __tablename__ = "qc_check_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    checkpoint_id: Mapped[int] = mapped_column(
        ForeignKey("qc_check_point.id"), nullable=False, index=True
    )
    # count / position / defect / color / visual_similarity
    rule_type: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_value_json: Mapped[Optional[dict]] = mapped_column(JSON)
    threshold_json: Mapped[Optional[dict]] = mapped_column(JSON)
    fail_condition_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    checkpoint: Mapped["QCCheckPoint"] = relationship("QCCheckPoint", back_populates="check_rules")


class QCInspectionJob(Base):
    """One QC inspection job."""
    __tablename__ = "qc_inspection_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku_id: Mapped[int] = mapped_column(ForeignKey("qc_product_sku.id"), nullable=False, index=True)
    standard_version_id: Mapped[int] = mapped_column(
        ForeignKey("qc_standard_version.id"), nullable=False, index=True
    )
    batch_no: Mapped[Optional[str]] = mapped_column(String(128))
    operator_id: Mapped[Optional[str]] = mapped_column(String(128))
    # created / media_uploaded / model_running / ai_done / review_required /
    # passed / failed / human_reviewed / final_report_generated
    inspection_status: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    # pad_local_mnn / server_model / human_only / hybrid
    runtime_type: Mapped[str] = mapped_column(String(32), nullable=False, default="server_model")
    checkpoint_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkpoint_observed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkpoint_pass_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkpoint_fail_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checkpoint_review_required_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    coverage_rate: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    has_unchecked_checkpoint: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    incidental_finding_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    major_incidental_finding_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    critical_incidental_finding_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    sku: Mapped["QCProductSku"] = relationship("QCProductSku", back_populates="inspection_jobs")
    standard_version: Mapped["QCStandardVersion"] = relationship(
        "QCStandardVersion", back_populates="inspection_jobs"
    )
    inspection_media: Mapped[list["QCInspectionMedia"]] = relationship(
        "QCInspectionMedia", back_populates="inspection_job"
    )
    model_results: Mapped[list["QCModelResult"]] = relationship(
        "QCModelResult", back_populates="inspection_job"
    )
    checkpoint_results: Mapped[list["QCCheckpointResult"]] = relationship(
        "QCCheckpointResult", back_populates="inspection_job"
    )
    incidental_findings: Mapped[list["QCIncidentalFinding"]] = relationship(
        "QCIncidentalFinding", back_populates="inspection_job"
    )
    human_reviews: Mapped[list["QCHumanReview"]] = relationship(
        "QCHumanReview", back_populates="inspection_job"
    )
    final_reports: Mapped[list["QCFinalReport"]] = relationship(
        "QCFinalReport", back_populates="inspection_job"
    )
    training_samples: Mapped[list["QCTrainingSample"]] = relationship(
        "QCTrainingSample", back_populates="inspection_job"
    )


class QCInspectionMedia(Base):
    """Bind inspection media to an inspection job."""
    __tablename__ = "qc_inspection_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_job_id: Mapped[int] = mapped_column(
        ForeignKey("qc_inspection_job.id"), nullable=False, index=True
    )
    media_asset_id: Mapped[int] = mapped_column(
        ForeignKey("qc_media_asset.id"), nullable=False, index=True
    )
    # front / side / back / detail / other
    view_type: Mapped[str] = mapped_column(String(64), nullable=False, default="front")
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    inspection_job: Mapped["QCInspectionJob"] = relationship(
        "QCInspectionJob", back_populates="inspection_media"
    )
    media_asset: Mapped["QCMediaAsset"] = relationship(
        "QCMediaAsset", back_populates="inspection_media"
    )


class QCModelResult(Base):
    """Model-level output for an inspection job."""
    __tablename__ = "qc_model_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_job_id: Mapped[int] = mapped_column(
        ForeignKey("qc_inspection_job.id"), nullable=False, index=True
    )
    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    model_version: Mapped[Optional[str]] = mapped_column(String(32))
    # pad_local_mnn / server_model / human_only / hybrid
    runtime_type: Mapped[str] = mapped_column(String(32), nullable=False, default="server_model")
    # pass / fail / review_required
    overall_result: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_confidence: Mapped[Optional[float]] = mapped_column(Float)
    no_guess_policy_applied: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    unsupported_checkpoints_json: Mapped[Optional[dict]] = mapped_column(JSON)
    low_confidence_checkpoints_json: Mapped[Optional[dict]] = mapped_column(JSON)
    manual_review_reason: Mapped[Optional[str]] = mapped_column(Text)
    raw_output_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    inspection_job: Mapped["QCInspectionJob"] = relationship(
        "QCInspectionJob", back_populates="model_results"
    )


class QCCheckpointResult(Base):
    """Result for each approved checkpoint in an inspection job."""
    __tablename__ = "qc_checkpoint_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_job_id: Mapped[int] = mapped_column(
        ForeignKey("qc_inspection_job.id"), nullable=False, index=True
    )
    checkpoint_id: Mapped[int] = mapped_column(
        ForeignKey("qc_check_point.id"), nullable=False, index=True
    )
    checkpoint_code: Mapped[str] = mapped_column(String(64), nullable=False)
    checkpoint_name: Mapped[str] = mapped_column(String(256), nullable=False)
    expected_json: Mapped[Optional[dict]] = mapped_column(JSON)
    observed_json: Mapped[Optional[dict]] = mapped_column(JSON)
    comparison_json: Mapped[Optional[dict]] = mapped_column(JSON)
    # pass / fail / review_required
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)
    # bbox / mask / crop / keypoint / color_sample / count_result / text_note / none
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSON)
    evidence_media_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qc_media_asset.id"), index=True
    )
    # observed / not_visible / occluded / low_confidence / unsupported
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="observed")
    failure_reason: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    inspection_job: Mapped["QCInspectionJob"] = relationship(
        "QCInspectionJob", back_populates="checkpoint_results"
    )
    checkpoint: Mapped["QCCheckPoint"] = relationship(
        "QCCheckPoint", back_populates="checkpoint_results"
    )


class QCIncidentalFinding(Base):
    """Abnormalities detected outside the approved checklist."""
    __tablename__ = "qc_incidental_finding"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_job_id: Mapped[int] = mapped_column(
        ForeignKey("qc_inspection_job.id"), nullable=False, index=True
    )
    media_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qc_media_asset.id"), index=True
    )
    # color_abnormality / surface_crack / contamination / deformation / missing_part /
    # material_abnormality / glue_overflow / oxidation / unknown
    finding_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # pearl / rhinestone / petal / metal_stamen / backing / whole_item / unknown
    target_part: Mapped[Optional[str]] = mapped_column(String(128))
    finding_text: Mapped[Optional[str]] = mapped_column(Text)
    # info / minor / major / critical
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="minor")
    confidence_score: Mapped[Optional[float]] = mapped_column(Float)
    is_within_approved_checklist: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    evidence_json: Mapped[Optional[dict]] = mapped_column(JSON)
    evidence_media_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qc_media_asset.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    inspection_job: Mapped["QCInspectionJob"] = relationship(
        "QCInspectionJob", back_populates="incidental_findings"
    )


class QCHumanReview(Base):
    """Human review or override record."""
    __tablename__ = "qc_human_review"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_job_id: Mapped[int] = mapped_column(
        ForeignKey("qc_inspection_job.id"), nullable=False, index=True
    )
    reviewer_id: Mapped[Optional[str]] = mapped_column(String(128))
    # confirmed / overridden / rejected / needs_reinspection
    review_status: Mapped[str] = mapped_column(String(32), nullable=False)
    original_result: Mapped[Optional[str]] = mapped_column(String(32))
    final_result: Mapped[str] = mapped_column(String(32), nullable=False)
    review_comment: Mapped[Optional[str]] = mapped_column(Text)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    inspection_job: Mapped["QCInspectionJob"] = relationship(
        "QCInspectionJob", back_populates="human_reviews"
    )


class QCFinalReport(Base):
    """Generated QC report."""
    __tablename__ = "qc_final_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_job_id: Mapped[int] = mapped_column(
        ForeignKey("qc_inspection_job.id"), nullable=False, index=True
    )
    # draft / final
    report_status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    # pass / fail / review_required
    final_result: Mapped[str] = mapped_column(String(32), nullable=False)
    summary_text: Mapped[Optional[str]] = mapped_column(Text)
    report_json: Mapped[Optional[dict]] = mapped_column(JSON)
    report_uri: Mapped[Optional[str]] = mapped_column(String(512))
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    inspection_job: Mapped["QCInspectionJob"] = relationship(
        "QCInspectionJob", back_populates="final_reports"
    )


class QCTrainingSample(Base):
    """Training data generated from real inspection and human review."""
    __tablename__ = "qc_training_sample"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    inspection_job_id: Mapped[int] = mapped_column(
        ForeignKey("qc_inspection_job.id"), nullable=False, index=True
    )
    media_asset_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qc_media_asset.id"), index=True
    )
    checkpoint_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qc_check_point.id"), index=True
    )
    # pass_case / fail_case / review_case / incidental_finding / correction
    sample_type: Mapped[str] = mapped_column(String(32), nullable=False)
    label_json: Mapped[Optional[dict]] = mapped_column(JSON)
    # ai_result / human_review / imported_dataset
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="ai_result")
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    inspection_job: Mapped["QCInspectionJob"] = relationship(
        "QCInspectionJob", back_populates="training_samples"
    )
    checkpoint: Mapped[Optional["QCCheckPoint"]] = relationship(
        "QCCheckPoint", back_populates="training_samples"
    )


class QCAuditEvent(Base):
    """Audit trail for all important state transitions."""
    __tablename__ = "qc_audit_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_id: Mapped[Optional[str]] = mapped_column(String(128))
    event_json: Mapped[Optional[dict]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
