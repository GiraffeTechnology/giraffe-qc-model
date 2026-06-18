"""QWEN QC Service — wraps the router for use by FastAPI endpoints."""
from __future__ import annotations

import logging
from typing import List, Optional

from src.config import llm_real_calls_enabled, qc_engine_mode
from src.qwen.base import QwenQCProvider
from src.qwen.router import QwenRouter
from src.qwen.schema import (
    CapturePhotoInput,
    InspectionContext,
    QcPointInput,
    QwenInspectionOutput,
    StandardPhotoInput,
)

logger = logging.getLogger(__name__)


class QwenQCService:
    """Service wrapper around QwenRouter for use in FastAPI routes.

    Provider selection is driven by QC_ENGINE_MODE:
      fake            → FakeCloudQwenProvider (default; CI-safe)
      cloud_qwen_dev  → DashScopeQwenProvider when LLM_ENABLE_REAL_CALLS=true;
                        falls back to FakeCloudQwenProvider when false
      on_device_first → FakeCloudQwenProvider until Android device is available
      backend_proxy   → DashScopeQwenProvider if LLM_ENABLE_REAL_CALLS=true

    An explicit cloud_provider constructor argument overrides mode selection.
    """

    def __init__(
        self,
        cloud_provider: Optional[QwenQCProvider] = None,
    ) -> None:
        self._router = QwenRouter()
        self._cloud_provider = cloud_provider

    def _get_provider(self) -> Optional[QwenQCProvider]:
        if self._cloud_provider is not None:
            return self._cloud_provider

        mode = qc_engine_mode()

        if mode in ("cloud_qwen_dev", "backend_proxy"):
            if llm_real_calls_enabled():
                try:
                    from src.qwen.dashscope_provider import DashScopeQwenProvider
                    provider = DashScopeQwenProvider()
                    # Mask key in log — show only first 8 chars
                    key = provider._api_key or ""
                    masked = (key[:8] + "****") if len(key) > 8 else "****"
                    logger.debug("QC engine mode=%s, provider=DashScope, key=%s", mode, masked)
                    return provider
                except Exception as exc:
                    logger.warning("DashScope provider unavailable (%s) — falling back to fake", exc)
                    return self._fake_provider()
            else:
                logger.debug("QC engine mode=%s but LLM_ENABLE_REAL_CALLS=false — using fake", mode)
                return self._fake_provider()

        # on_device_first, fake, or unknown — safe default
        return self._fake_provider()

    @staticmethod
    def _fake_provider() -> QwenQCProvider:
        from src.qwen.fake_providers import FakeCloudQwenProvider
        return FakeCloudQwenProvider()

    def run_inspection(
        self,
        standard_photos: List[StandardPhotoInput],
        captured_photo: CapturePhotoInput,
        qc_points: List[QcPointInput],
        context: InspectionContext,
    ) -> QwenInspectionOutput:
        provider = self._get_provider()
        return self._router.route(
            standard_photos=standard_photos,
            captured_photo=captured_photo,
            qc_points=qc_points,
            context=context,
            cloud_provider=provider,
        )
