"""The Pad ↔ Jetson inference request/response contract (§4).

Jetson is **stateless per request** (§3): every request carries the full
detection-point spec inline (including ``expected_value``, ``pass_criteria`` and
``regions``) plus ``standard_revision_id`` / ``bundle_version`` — the Jetson
never needs a separately installed bundle, which eliminates Pad↔Jetson version
skew.

These pydantic models are the single shared definition of that contract, used by
the mock Jetson runner to validate incoming requests and by the Pad-side
orchestration (and Server-side helpers) to build/validate them. Jetson's
``per_point_results`` is **evidence, not authority** — the Server still
recomputes the final verdict (S4).
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, field_validator

from src.qc_model.jetson import constants as C


class Region(BaseModel):
    image_id: str
    x: float = 0
    y: float = 0
    w: float = 0
    h: float = 0


class DetectionPointSpec(BaseModel):
    point_code: str
    label: str = ""
    description: str = ""
    method_hint: str = ""
    expected_value: str = ""
    pass_criteria: str = ""
    severity: str = "major"
    regions: list[Region] = []


class InferenceRequest(BaseModel):
    """Pad → Jetson (LAN)."""

    job_id: str
    standard_revision_id: str
    bundle_version: str = ""
    # A reference/URI or inline-encoded captured frame. The bytes never touch
    # the Server — this is a Pad↔Jetson LAN payload.
    image: str
    detection_points: list[DetectionPointSpec]

    @field_validator("detection_points")
    @classmethod
    def _non_empty(cls, v: list[DetectionPointSpec]) -> list[DetectionPointSpec]:
        if not v:
            raise ValueError("detection_points must not be empty")
        return v


class PerPointResult(BaseModel):
    point_code: str
    # pass | fail | uncertain
    result: str
    confidence: float = 0.0
    evidence: str = ""

    @field_validator("result")
    @classmethod
    def _valid_result(cls, v: str) -> str:
        if v not in C.INFERENCE_RESULTS:
            raise ValueError(f"invalid result: {v}")
        return v


class InferenceResponse(BaseModel):
    """Jetson → Pad. Evidence only; not a final verdict."""

    job_id: str
    per_point_results: list[PerPointResult]


def validate_request(payload: dict) -> InferenceRequest:
    """Parse+validate a raw request dict. Raises ``pydantic.ValidationError``."""
    return InferenceRequest.model_validate(payload)
