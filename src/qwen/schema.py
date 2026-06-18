"""Pydantic v2 schemas for the QWEN QC inspection pipeline."""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


class QcPointInput(BaseModel):
    qc_point_id: str
    qc_point_code: str
    name: str
    description: str
    roi_json: dict | None = None
    rule_type: str | None = None


class StandardPhotoInput(BaseModel):
    photo_id: str
    local_path: str
    angle: str | None = None


class CapturePhotoInput(BaseModel):
    photo_id: str
    local_path: str


class InspectionContext(BaseModel):
    tenant_id: str
    sku_id: str
    standard_id: str
    inspection_id: str


class InspectionItemResult(BaseModel):
    qc_point_id: str
    qc_point_code: str
    name: str
    result: Literal["pass", "fail", "review_required"]
    confidence: float
    reason: str
    evidence: dict = Field(default_factory=dict)


class FallbackInfo(BaseModel):
    used: bool = False
    reason: str | None = None


class QwenInspectionOutput(BaseModel):
    overall_result: Literal["pass", "fail", "review_required"]
    engine: str  # "local_qwen_mnn" | "cloud_qwen"
    model_name: str
    confidence: float
    items: list[InspectionItemResult]
    fallback: FallbackInfo
    summary: str = ""
