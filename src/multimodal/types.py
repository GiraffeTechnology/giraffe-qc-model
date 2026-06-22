"""Canonical provider-neutral QC schemas."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


# ── Provider interface types ────────────────────────────────────────────────

class MultimodalMessagePart(BaseModel):
    type: Literal["text", "image", "video", "json"]
    text: str | None = None
    image_path: str | None = None
    image_base64: str | None = None
    video_path: str | None = None
    json_data: dict[str, Any] | None = None


class MultimodalRequest(BaseModel):
    capability: str
    prompt_version: str
    messages: list[MultimodalMessagePart]
    response_schema_name: str
    response_schema: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)
    max_output_tokens: int = 2048
    temperature: float = 0.0


class MultimodalRawResponse(BaseModel):
    provider: str
    model: str
    raw_text: str
    raw_json: dict[str, Any] | None = None
    latency_ms: int | None = None
    token_usage: dict[str, Any] | None = None
    http_status: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Image quality ─────────────────────────────────────────────────────────────────

class ImageQualityIssue(BaseModel):
    issue_type: Literal[
        "blur", "low_light", "overexposure", "occlusion",
        "wrong_angle", "too_far", "too_close", "background_noise", "unknown",
    ]
    severity: Literal["low", "medium", "high"]
    description: str


class ImageQualityAssessment(BaseModel):
    usable: bool
    confidence: float
    issues: list[ImageQualityIssue] = []
    recommended_action: Literal["proceed", "retake", "manual_review"]
    reason: str


# ── Visual regions / defect grounding ────────────────────────────────────────────

class VisualRegion(BaseModel):
    label: str
    bbox: list[float] | None = None   # [x1, y1, x2, y2] normalized 0-1
    point: list[float] | None = None  # [x, y] normalized 0-1
    confidence: float
    description: str


class DefectGroundingResult(BaseModel):
    qc_point_id: str
    defect_type: str
    severity: Literal["minor", "major", "critical", "unknown"]
    visual_regions: list[VisualRegion]
    confidence: float
    description_zh: str
    description_en: str


# ── OCR ────────────────────────────────────────────────────────────────────────────

class OCRExtractionResult(BaseModel):
    detected_text: list[str]
    labels: list[dict[str, Any]] = []
    confidence: float
    issues: list[str] = []


# ── SKU match ──────────────────────────────────────────────────────────────────────

class SkuCandidate(BaseModel):
    sku_id: str
    standard_id: str
    score: float
    reason: str


class SkuMatchResult(BaseModel):
    matched: bool
    top_candidates: list[SkuCandidate]
    recommended_action: Literal["proceed", "manual_review", "wrong_sku"]
    confidence: float


# ── Evidence ───────────────────────────────────────────────────────────────────────

class QCEvidence(BaseModel):
    image_quality: ImageQualityAssessment | None = None
    visual_regions: list[VisualRegion] = []
    defect_grounding: list[DefectGroundingResult] = []
    ocr: OCRExtractionResult | None = None
    standard_reference: str = ""
    production_observation: str = ""
    model_reasoning_summary: str = ""
    review_required_reason: str | None = None
    raw_provider_metadata: dict[str, Any] = Field(default_factory=dict)


# ── QC result ────────────────────────────────────────────────────────────────────────

class QCItemResult(BaseModel):
    qc_point_id: str
    qc_point_code: str
    name: str
    result: Literal["pass", "fail", "review_required"]
    confidence: float
    reason: str
    evidence: QCEvidence = Field(default_factory=QCEvidence)


class QCInspectionResult(BaseModel):
    overall_result: Literal["pass", "fail", "review_required"]
    engine: str
    provider: str
    model_name: str
    confidence: float
    items: list[QCItemResult]
    fallback: dict[str, Any] = Field(default_factory=dict)
    summary: str
    capability_versions: dict[str, str] = Field(default_factory=dict)


# ── Report ────────────────────────────────────────────────────────────────────────────

class QCReport(BaseModel):
    report_zh: str
    report_en: str
    executive_summary_zh: str
    executive_summary_en: str
