"""Provider-compatible abstraction layer.

Product logic imports only :mod:`src.qc_model.providers.base` and the
:mod:`src.qc_model.providers.registry`. Concrete provider classes
(Qwen3.5-VL, mainstream-LLM/VLM adapters, mocks) are resolved lazily by the
registry so that no product service depends directly on a vendor class.
"""
from src.qc_model.providers.base import (
    VisionLanguageModelProvider,
    VisualInspectionRequest,
    VisualInspectionResponse,
    ProviderCheckpointResult,
    ProviderIncidentalFinding,
    ProviderCaptureQuality,
)

__all__ = [
    "VisionLanguageModelProvider",
    "VisualInspectionRequest",
    "VisualInspectionResponse",
    "ProviderCheckpointResult",
    "ProviderIncidentalFinding",
    "ProviderCaptureQuality",
]
