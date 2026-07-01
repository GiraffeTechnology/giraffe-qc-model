"""Mainstream LLM/VLM compatibility adapter stub.

Demonstrates (and lets tests prove) that the product is NOT Qwen-bound: a
mainstream provider — e.g. an OpenAI/Gemini/Anthropic-style VLM — can satisfy
the exact same :class:`VisionLanguageModelProvider` interface.

This is a stub adapter: it wraps a vendor-neutral ``call_fn`` that returns a
list of ``{"code", "result", "evidence"}`` dicts. A real adapter would map
the provider's HTTP/SDK response into that shape. The point of Phase 1 is to
prove the seam holds, not to ship a production HTTP client.
"""
from __future__ import annotations

from typing import Callable

from src.qc_model.providers.base import (
    ProviderCaptureQuality,
    ProviderCheckpointResult,
    VisionLanguageModelProvider,
    VisualInspectionRequest,
    VisualInspectionResponse,
)


class MainstreamVLMAdapter(VisionLanguageModelProvider):
    """Adapter for any mainstream LLM/VLM exposed through ``call_fn``.

    ``call_fn(request) -> list[dict]`` where each dict has at least ``code``
    and ``result`` (and optionally ``evidence``, ``confidence``).
    """

    def __init__(
        self,
        call_fn: Callable[[VisualInspectionRequest], list[dict]],
        provider_name: str = "mainstream_vlm",
        model_name: str = "mainstream-vlm",
    ) -> None:
        self._call_fn = call_fn
        self._provider_name = provider_name
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def inspect(self, request: VisualInspectionRequest) -> VisualInspectionResponse:
        try:
            raw_items = self._call_fn(request)
        except Exception as exc:  # fail closed, never raise to product logic
            return VisualInspectionResponse(
                overall_result="review_required",
                checkpoint_results=[],
                provider=self._provider_name,
                model=self._model_name,
                valid=False,
                error=f"{type(exc).__name__}: {exc}",
            )

        results = [
            ProviderCheckpointResult(
                code=str(item.get("code", "")),
                result=str(item.get("result", "review_required")),
                visual_evidence=str(item.get("evidence", "")),
                confidence=float(item.get("confidence", 0.0)),
                requires_human_review=item.get("result") == "review_required",
            )
            for item in raw_items
        ]
        overall = (
            "fail"
            if any(r.result == "fail" for r in results)
            else "review_required"
            if any(r.result == "review_required" for r in results)
            else "pass"
        )
        return VisualInspectionResponse(
            overall_result=overall,
            checkpoint_results=results,
            provider=self._provider_name,
            model=self._model_name,
            capture_quality=ProviderCaptureQuality(acceptable=True),
            valid=True,
            raw_summary="mainstream adapter response",
        )
