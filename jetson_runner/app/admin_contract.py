"""Architecture v2 Administrator Xavier request/response models.

These models implement ``docs/api-contracts/xavier-admin-runner-api.md``.
They are deliberately separate from the legacy Pad-to-Jetson Operator
contract in ``src.qc_model.jetson.contract`` so WS4 can retire that path
without removing the Administrator MNN service.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ImageSpec(ContractModel):
    image_id: str = Field(min_length=1)
    part: str = Field(min_length=1)
    sha256: str
    content_type: str
    encoded_bytes: int = Field(gt=0)

    @field_validator("sha256")
    @classmethod
    def _digest(cls, value: str) -> str:
        value = value.lower()
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("sha256 must be 64 lowercase hexadecimal characters")
        return value


class Region(ContractModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _inside_image(self):
        if self.x + self.w > 1.0 or self.y + self.h > 1.0:
            raise ValueError("region must fit inside normalized image bounds")
        return self


class AdminDetectionPoint(ContractModel):
    point_code: str = Field(min_length=1)
    image_id: str = Field(min_length=1)
    label: str = ""
    description: str = ""
    expected_value: str = ""
    pass_criteria: str = ""
    severity: str = "major"
    regions: list[Region] = Field(default_factory=list)
    expected_features: Optional[dict[str, Any]] = None
    cv_config: Optional[dict[str, Any]] = None
    cv_status: Literal["not_configured", "completed", "failed"] = "not_configured"
    cv_analysis: Optional[dict[str, Any]] = None


class AdminRecognitionRequest(ContractModel):
    schema_version: Literal["2.0"]
    request_id: str = Field(min_length=1)
    workflow: Literal[
        "authoring_validation", "qualification_review", "admin_recheck"
    ]
    standard_revision_id: str = Field(min_length=1)
    bundle_version: str = ""
    images: list[ImageSpec]
    detection_points: list[AdminDetectionPoint]

    @model_validator(mode="after")
    def _references(self):
        if not self.images:
            raise ValueError("images must not be empty")
        if not self.detection_points:
            raise ValueError("detection_points must not be empty")
        image_ids = [image.image_id for image in self.images]
        if len(image_ids) != len(set(image_ids)):
            raise ValueError("image_id values must be unique")
        point_codes = [point.point_code for point in self.detection_points]
        if len(point_codes) != len(set(point_codes)):
            raise ValueError("point_code values must be unique")
        known = set(image_ids)
        missing = sorted({point.image_id for point in self.detection_points} - known)
        if missing:
            raise ValueError(f"detection points reference unknown image ids: {missing}")
        return self


class EvidenceRegion(ContractModel):
    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def _inside_image(self):
        if self.x + self.w > 1.0 or self.y + self.h > 1.0:
            raise ValueError("evidence region must fit inside normalized image bounds")
        return self


class AdminPointResult(ContractModel):
    point_code: str
    result: Literal["pass", "fail", "uncertain"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: str = ""
    evidence_regions: list[EvidenceRegion] = Field(default_factory=list)
    cv_status: Literal["not_configured", "completed", "failed"] = "not_configured"
    cv_analysis: Optional[dict[str, Any]] = None


class RuntimeIdentity(ContractModel):
    engine: Literal["mnn"] = "mnn"
    model_name: str
    model_revision: str = "unvalidated"
    adapter_mode: Literal["real", "mock"]


class RecognitionTiming(ContractModel):
    request_received_at: str
    cv_started_at: Optional[str] = None
    cv_completed_at: Optional[str] = None
    inference_started_at: str
    inference_completed_at: str
    response_sent_at: str


class AdminRecognitionResponse(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    request_id: str
    status: Literal["completed"] = "completed"
    point_results: list[AdminPointResult]
    runtime: RuntimeIdentity
    timing: RecognitionTiming
    mock: bool


class ProcessingStatus(ContractModel):
    schema_version: Literal["2.0"] = "2.0"
    request_id: str
    status: Literal["processing"] = "processing"
    retry_after_ms: int = 250


def validate_admin_request(payload: dict) -> AdminRecognitionRequest:
    return AdminRecognitionRequest.model_validate(payload)
