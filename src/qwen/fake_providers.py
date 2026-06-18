"""Fake QWEN QC providers for testing.

These providers do NOT import or call any real MNN or DashScope API.
Use them in tests to avoid real network/model calls.
"""
from __future__ import annotations

import json
from typing import List

from src.qwen.base import QwenQCProvider
from src.qwen.schema import (
    CapturePhotoInput,
    FallbackInfo,
    InspectionContext,
    InspectionItemResult,
    QcPointInput,
    QwenInspectionOutput,
    StandardPhotoInput,
)


class FakeCloudQwenProvider(QwenQCProvider):
    """Test provider that always returns a deterministic pass result.

    All QC points are marked as pass with confidence 1.0.
    """

    @property
    def engine_name(self) -> str:
        return "fake_cloud_qwen"

    def inspect(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        items = [
            InspectionItemResult(
                qc_point_id=p.qc_point_id,
                qc_point_code=p.qc_point_code,
                name=p.name,
                result="pass",
                confidence=1.0,
                reason="Fake provider: always pass",
                evidence={},
            )
            for p in qc_points
        ]
        return QwenInspectionOutput(
            overall_result="pass",
            engine="fake_cloud_qwen",
            model_name="fake-qwen-vl-v1",
            confidence=1.0,
            items=items,
            fallback=FallbackInfo(used=False),
            summary="Fake inspection: all points passed",
        )


class FailingQwenProvider(QwenQCProvider):
    """Test provider that always raises RuntimeError."""

    @property
    def engine_name(self) -> str:
        return "failing_qwen"

    def inspect(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        raise RuntimeError("FailingQwenProvider: intentional failure for testing")


class TimeoutQwenProvider(QwenQCProvider):
    """Test provider that always raises TimeoutError."""

    @property
    def engine_name(self) -> str:
        return "timeout_qwen"

    def inspect(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        raise TimeoutError("TimeoutQwenProvider: intentional timeout for testing")


class InvalidJsonQwenProvider(QwenQCProvider):
    """Test provider that returns invalid JSON output."""

    @property
    def engine_name(self) -> str:
        return "invalid_json_qwen"

    def inspect(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        # This provider's inspect returns a "raw" string, but to simulate
        # what happens when the parser receives invalid JSON, we call the parser
        # directly — but here we just return a valid schema object with the raw text.
        # The intended use is: pass the raw string "not json at all" to parse_qwen_output
        # to test parser behavior. This provider simulates that scenario.
        from src.qwen.parser import parse_qwen_output
        return parse_qwen_output(
            "not json at all",
            [p.qc_point_id for p in qc_points],
            "invalid_json_qwen",
        )
