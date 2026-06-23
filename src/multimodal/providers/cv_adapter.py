"""
CvAdapterProvider: thin adapter over the existing OpenCV SSIM comparator.

Selected when MULTIMODAL_PROVIDER=cv. Supports image_quality and sku_match
capabilities only. Returns review_required gracefully when cv2 is not installed
or the capability is not handled.

The cv2 import is deferred to generate() so the provider can be registered
and instantiated without requiring opencv-python at import time.
"""

from __future__ import annotations

import time
from typing import Any

try:
    from .base import MultimodalProvider
except ImportError:
    class MultimodalProvider:  # type: ignore[no-redef]
        """Stub base when multimodal layer is not yet available."""

try:
    from ..types import MultimodalRawResponse
except ImportError:
    MultimodalRawResponse = Any  # type: ignore[assignment,misc]

_CV_SUPPORTED_CAPABILITIES = frozenset({"image_quality", "sku_match"})


class CvAdapterProvider(MultimodalProvider):
    """
    Adapter for the OpenCV structural-similarity comparator.

    Capabilities:
      image_quality — SSIM-based usability check (stub: returns review_required)
      sku_match     — feature-match-based candidate ranking (stub: returns review_required)

    All other capabilities return review_required immediately.
    When cv2 is not installed, all capabilities return review_required.
    """

    @property
    def provider_name(self) -> str:
        return "cv"

    @property
    def model_name(self) -> str:
        return "opencv_ssim"

    def generate(self, request: Any) -> Any:
        start = time.monotonic()
        capability = getattr(request, "capability", "")

        if capability not in _CV_SUPPORTED_CAPABILITIES:
            return _make_response(
                self.provider_name, self.model_name,
                {"overall_result": "review_required",
                 "reason": f"cv_adapter_does_not_support_capability:{capability}"},
                int((time.monotonic() - start) * 1000), 200,
                {"cv_supported_capabilities": list(_CV_SUPPORTED_CAPABILITIES)},
            )

        try:
            import cv2  # type: ignore[import]  # noqa: F401
            cv_available = True
        except ImportError:
            cv_available = False

        if not cv_available:
            return _make_response(
                self.provider_name, self.model_name,
                {"overall_result": "review_required", "reason": "cv2_not_installed"},
                int((time.monotonic() - start) * 1000), 503,
                {"cv_available": False},
            )

        # Real CV comparison logic is wired here once the comparator is ready.
        # Stub returns review_required until the OpenCV pipeline is connected.
        return _make_response(
            self.provider_name, self.model_name,
            {"overall_result": "review_required", "reason": "cv_comparator_not_yet_wired"},
            int((time.monotonic() - start) * 1000), 200,
            {"cv_available": True},
        )


def _make_response(
    provider: str, model: str, raw_json: dict,
    latency_ms: int, http_status: int, metadata: dict,
) -> Any:
    try:
        from ..types import MultimodalRawResponse
        return MultimodalRawResponse(
            provider=provider, model=model,
            raw_text="", raw_json=raw_json,
            latency_ms=latency_ms, http_status=http_status, metadata=metadata,
        )
    except ImportError:
        return {"provider": provider, **raw_json}
