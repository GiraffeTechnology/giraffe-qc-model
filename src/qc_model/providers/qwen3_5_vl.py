"""Default Qwen3.5-VL provider adapter.

This is the *default* provider for both product runtime profiles
(``qwen3.5-vl-2b-mnn`` and ``qwen3.5-vl-8b-int4``), but it is just one
implementation of :class:`VisionLanguageModelProvider`. Product logic never
imports this class directly — it goes through
:mod:`src.qc_model.providers.registry`.

Phase 1 boundary: this adapter does NOT perform real inference and does NOT
certify qwen3.5-vl accuracy. With no real backend configured it fails closed
to ``review_required`` (``valid=False``). Real HTTP/MNN wiring is a later
phase; the physical Android Pad MNN runtime is explicitly out of scope.
"""
from __future__ import annotations

from src.qc_model.providers.base import (
    VisionLanguageModelProvider,
    VisualInspectionRequest,
    VisualInspectionResponse,
)


class Qwen35VLProvider(VisionLanguageModelProvider):
    """Default Qwen3.5-VL adapter for a given runtime profile model."""

    def __init__(self, model: str = "qwen3.5-vl-8b-int4") -> None:
        self._model = model

    @property
    def provider_name(self) -> str:
        return "qwen3_5_vl"

    @property
    def model_name(self) -> str:
        return self._model

    def inspect(self, request: VisualInspectionRequest) -> VisualInspectionResponse:
        # Phase 1: no real backend is wired. Fail closed to review_required so
        # the finalizer never emits an unverified pass. Real inference wiring
        # is a later phase and is gated behind explicit configuration.
        return VisualInspectionResponse(
            overall_result="review_required",
            checkpoint_results=[],
            provider=self.provider_name,
            model=self._model,
            valid=False,
            error="qwen3.5-vl real inference backend not configured in Phase 1",
            raw_summary="qwen3.5-vl adapter (no backend configured)",
        )
