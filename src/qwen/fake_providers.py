"""Fake QWEN QC providers for testing.

These providers do NOT import or call any real MNN or DashScope API.
Use them in tests to avoid real network/model calls.
"""
from __future__ import annotations

import json
from typing import List

from src.config import fake_provider_allowed
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
        _ensure_fake_provider_allowed()
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
        _ensure_fake_provider_allowed()
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
        _ensure_fake_provider_allowed()
        raise TimeoutError("TimeoutQwenProvider: intentional timeout for testing")


class FakeFailCloudQwenProvider(QwenQCProvider):
    """Test provider that returns a deterministic fail result (no exception)."""

    @property
    def engine_name(self) -> str:
        return "fake_fail_cloud_qwen"

    def inspect(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        _ensure_fake_provider_allowed()
        items = [
            InspectionItemResult(
                qc_point_id=p.qc_point_id,
                qc_point_code=p.qc_point_code,
                name=p.name,
                result="fail",
                confidence=0.95,
                reason="Fake provider: always fail",
                evidence={},
            )
            for p in qc_points
        ]
        return QwenInspectionOutput(
            overall_result="fail",
            engine="fake_fail_cloud_qwen",
            model_name="fake-qwen-vl-v1",
            confidence=0.95,
            items=items,
            fallback=FallbackInfo(used=False),
            summary="Fake inspection: all points failed",
        )


class NotProvisionedQwenProvider(QwenQCProvider):
    """Test provider that raises UnsupportedOperationError (model not on device)."""

    @property
    def engine_name(self) -> str:
        return "not_provisioned_qwen"

    def inspect(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        _ensure_fake_provider_allowed()
        raise UnsupportedOperationError("on_device_model_not_provisioned")


class UnsupportedOperationError(Exception):
    """Raised when the on-device model is not provisioned."""


class InvalidJsonQwenProvider(QwenQCProvider):
    """Test provider that returns invalid JSON output (simulates parse failure path)."""

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
        _ensure_fake_provider_allowed()
        from src.qwen.parser import parse_qwen_output
        return parse_qwen_output(
            "not json at all",
            [p.qc_point_id for p in qc_points],
            "invalid_json_qwen",
        )


def _ensure_fake_provider_allowed() -> None:
    if not fake_provider_allowed():
        raise RuntimeError(
            "Fake QWEN providers are disabled outside APP_ENV=test or "
            "QC_ALLOW_TEST_ADAPTER=true."
        )
