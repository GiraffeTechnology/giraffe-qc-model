"""Abstract Vision-Language-Model provider interface.

This is the single seam between Giraffe QC Model product logic and any
concrete LLM/VLM backend. The PRD requires:

    class VisionLanguageModelProvider:
        def inspect(self, request: VisualInspectionRequest) -> VisualInspectionResponse:
            ...

Product services (runner, finalizer, lifecycle, UI) must depend on this
abstraction and never import a Qwen-specific class directly. A mocked
provider, a mainstream-LLM/VLM-compatible adapter, and the default
Qwen3.5-VL adapter all satisfy the same interface.

The request/response objects are intentionally plain dataclasses (not tied
to any vendor SDK) so that adapters for mainstream providers can be written
without leaking vendor types into product code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class VisualInspectionRequest:
    """Vendor-neutral request handed to a VLM provider.

    Carries only the *confirmed* QC context. Building this object is the
    runner's job; preconditions (confirmed Training Pack, confirmed
    categories, readable images, …) are enforced before a provider is ever
    called.
    """

    sku_id: str
    station_id: str
    capture_protocol: dict[str, Any]
    reference_image_paths: list[str]
    inspection_image_paths: list[str]
    # Each entry is a confirmed detection point projected to the fields the
    # model needs: code, name, checkpoint_category, normal/defect features,
    # known pseudo-defects, decision rule, review_required conditions.
    detection_points: list[dict[str, Any]]
    reference_descriptions: list[str] = field(default_factory=list)
    inspection_context: dict[str, Any] = field(default_factory=dict)
    output_schema_hint: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderCheckpointResult:
    code: str
    result: str  # "pass" | "fail" | "review_required" (raw model claim)
    visual_evidence: str = ""
    normal_vs_defect_reasoning: str = ""
    pseudo_defect_analysis: str = ""
    confidence: float = 0.0
    requires_human_review: bool = False


@dataclass
class ProviderIncidentalFinding:
    description: str
    severity: str = "minor"  # "minor" | "major" | "critical"
    visual_evidence: str = ""
    requires_human_review: bool = False


@dataclass
class ProviderCaptureQuality:
    acceptable: bool = True
    issues: list[str] = field(default_factory=list)


@dataclass
class VisualInspectionResponse:
    """Vendor-neutral structured response.

    This is the *raw model claim*. It is never trusted as-is: the
    deterministic finalizer re-derives the authoritative overall result from
    the checkpoint-level results and the safety guardrails.

    ``valid`` is False when the provider could not return parseable
    structured output. A False here forces ``review_required`` downstream.
    """

    overall_result: str  # raw model claim, NOT authoritative
    checkpoint_results: list[ProviderCheckpointResult]
    provider: str
    model: str
    confidence: float = 0.0
    incidental_findings: list[ProviderIncidentalFinding] = field(default_factory=list)
    capture_quality: ProviderCaptureQuality = field(default_factory=ProviderCaptureQuality)
    valid: bool = True
    error: str | None = None
    raw_summary: str = ""


class VisionLanguageModelProvider(ABC):
    """All VLM providers (Qwen3.5-VL, mainstream adapters, mocks) subclass this."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Stable provider identifier, e.g. ``qwen3_5_vl`` or ``openai_vlm``."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Concrete model identifier, e.g. ``qwen3.5-vl-8b-int4``."""
        ...

    @abstractmethod
    def inspect(self, request: VisualInspectionRequest) -> VisualInspectionResponse:
        """Run one visual inspection.

        Implementations must NEVER raise to signal an inference failure —
        they return ``VisualInspectionResponse(valid=False, ...)`` so the
        finalizer can fail closed to ``review_required``. If an
        implementation does raise, the runner converts it to a fail-closed
        ``review_required`` result.
        """
        ...
