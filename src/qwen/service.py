"""QWEN QC Service — wraps the router for use by FastAPI endpoints."""
from __future__ import annotations

import os
from typing import List, Optional

from src.qwen.base import QwenQCProvider
from src.qwen.router import QwenRouter
from src.qwen.schema import (
    CapturePhotoInput,
    InspectionContext,
    QcPointInput,
    QwenInspectionOutput,
    StandardPhotoInput,
)


def _cloud_enabled() -> bool:
    return os.getenv("QWEN_CLOUD_ENABLED", "false").lower() == "true"


class QwenQCService:
    """Service wrapper around QwenRouter for use in FastAPI routes.

    Manages provider selection based on runtime configuration.
    When QWEN_CLOUD_ENABLED is false, uses FakeCloudQwenProvider so
    no real API calls are made.
    """

    def __init__(
        self,
        cloud_provider: Optional[QwenQCProvider] = None,
    ) -> None:
        self._router = QwenRouter()
        self._cloud_provider = cloud_provider

    def _get_provider(self) -> Optional[QwenQCProvider]:
        """Get the active cloud provider, or FakeCloudQwenProvider if cloud is disabled."""
        if self._cloud_provider is not None:
            return self._cloud_provider

        if _cloud_enabled():
            # Try to build DashScope provider
            try:
                from src.qwen.dashscope_provider import DashScopeQwenProvider
                return DashScopeQwenProvider()
            except Exception:
                return None
        else:
            # Use fake provider so tests/dev never hit real API
            from src.qwen.fake_providers import FakeCloudQwenProvider
            return FakeCloudQwenProvider()

    def run_inspection(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        """Run a QC inspection through the router.

        Args:
            standard_photos: Standard reference photos
            captured_photo: Production capture photo
            qc_points: QC criteria to evaluate
            context: Inspection context

        Returns:
            QwenInspectionOutput
        """
        provider = self._get_provider()
        return self._router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=provider,
        )
