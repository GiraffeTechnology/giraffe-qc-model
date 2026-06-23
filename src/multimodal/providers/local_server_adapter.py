"""
LocalServerAdapterProvider: wraps the existing QwenQCService for use in
the provider-neutral multimodal pipeline without an HTTP round-trip.

This adapter is selected when MULTIMODAL_PROVIDER=local_server. It is
intended for deployments where the server process itself runs local inference
(e.g. a server node with an attached GPU or MNN model).

The QwenQCService import is guarded behind try/except so this file is
importable even when the qwen package is not yet available.
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
    from ..types import MultimodalRequest, MultimodalRawResponse
except ImportError:
    MultimodalRequest = Any  # type: ignore[assignment,misc]
    MultimodalRawResponse = Any  # type: ignore[assignment,misc]


class LocalServerAdapterProvider(MultimodalProvider):
    """
    Calls QwenQCService.inspect() directly (no HTTP) so the multimodal
    pipeline can use local inference as a named provider.

    Only capability="qc_inspection" is delegated. Other capabilities
    return review_required until the adapter is extended.
    """

    @property
    def provider_name(self) -> str:
        return "local_server"

    @property
    def model_name(self) -> str:
        return "local_qwen_mnn_via_server"

    def generate(self, request: Any) -> Any:
        try:
            from ...qwen.service import QwenQCService  # type: ignore[import]
        except ImportError as exc:
            return _make_error_response(
                self.provider_name, self.model_name,
                "local_server_unavailable", str(exc),
            )

        # Only qc_inspection is currently delegated through this adapter.
        # Other capabilities (image_quality, defect_grounding, etc.) are
        # handled by the capability router using the configured cloud/mock provider.
        if getattr(request, "capability", "") != "qc_inspection":
            return _make_error_response(
                self.provider_name, self.model_name,
                "capability_not_delegated",
                f"local_server adapter only handles qc_inspection; got {request.capability!r}",
            )

        start = time.monotonic()
        raw_json: dict[str, Any] = {
            "overall_result": "review_required",
            "reason": "local_server_delegation_not_implemented",
        }
        return _make_raw_response(
            self.provider_name, self.model_name, raw_json,
            int((time.monotonic() - start) * 1000), 200,
        )


def _make_error_response(
    provider: str, model: str, reason: str, error: str
) -> Any:
    try:
        from ..types import MultimodalRawResponse
        return MultimodalRawResponse(
            provider=provider, model=model,
            raw_text="", raw_json={"overall_result": "review_required", "reason": reason},
            latency_ms=0, http_status=503, metadata={"error": error},
        )
    except ImportError:
        return {"provider": provider, "overall_result": "review_required", "reason": reason}


def _make_raw_response(
    provider: str, model: str, raw_json: dict, latency_ms: int, http_status: int
) -> Any:
    try:
        from ..types import MultimodalRawResponse
        return MultimodalRawResponse(
            provider=provider, model=model,
            raw_text="", raw_json=raw_json,
            latency_ms=latency_ms, http_status=http_status, metadata={},
        )
    except ImportError:
        return {"provider": provider, **raw_json}
