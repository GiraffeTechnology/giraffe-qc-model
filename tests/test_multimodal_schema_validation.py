"""Tests for canonical QC schema validation."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.multimodal.types import (
    DefectGroundingResult,
    ImageQualityAssessment,
    ImageQualityIssue,
    MultimodalRequest,
    OCRExtractionResult,
    QCEvidence,
    QCInspectionResult,
    QCItemResult,
    SkuMatchResult,
    VisualRegion,
)


def test_image_quality_assessment_valid():
    iq = ImageQualityAssessment(
        usable=True,
        confidence=0.9,
        issues=[],
        recommended_action="proceed",
        reason="OK",
    )
    assert iq.usable is True
    assert iq.confidence == 0.9


def test_image_quality_issue_invalid_type_raises():
    with pytest.raises(ValidationError):
        ImageQualityIssue(issue_type="invalid_type_xyz", severity="low", description="x")


def test_visual_region_valid():
    r = VisualRegion(label="scratch", bbox=[0.1, 0.2, 0.5, 0.6], confidence=0.85, description="visible scratch")
    assert r.bbox == [0.1, 0.2, 0.5, 0.6]


def test_qc_item_result_valid():
    item = QCItemResult(
        qc_point_id="p1",
        qc_point_code="C001",
        name="Surface check",
        result="pass",
        confidence=0.92,
        reason="No defects",
    )
    assert item.result == "pass"


def test_qc_item_result_invalid_result_raises():
    with pytest.raises(ValidationError):
        QCItemResult(
            qc_point_id="p1",
            qc_point_code="C001",
            name="test",
            result="unknown_result",
            confidence=0.5,
            reason="test",
        )


def test_qc_inspection_result_valid():
    result = QCInspectionResult(
        overall_result="pass",
        engine="multimodal_qc",
        provider="mock",
        model_name="mock-v1",
        confidence=0.9,
        items=[],
        summary="all pass",
    )
    assert result.overall_result == "pass"


def test_confidence_bounds():
    """Confidence values outside 0-1 should still be accepted by schema (clamped by validators)."""
    from src.multimodal.parsers.validators import clamp_confidence
    assert clamp_confidence(1.5) == 1.0
    assert clamp_confidence(-0.1) == 0.0
    assert clamp_confidence(0.75) == 0.75


def test_multimodal_request_valid():
    from src.multimodal.types import MultimodalMessagePart
    req = MultimodalRequest(
        capability="qc_inspection",
        prompt_version="qc-inspection-v2",
        messages=[MultimodalMessagePart(type="text", text="hello")],
        response_schema_name="QCInspectionResult",
        response_schema={},
    )
    assert req.capability == "qc_inspection"
