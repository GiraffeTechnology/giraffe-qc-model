"""Abstract base class for all LLM providers used by giraffe-qc-model."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImageCompareResult:
    overall_result: str          # "pass" | "needs_fix" | "reject" | "unknown"
    similarity_score: float      # 0.0-1.0
    severity: str                # "low" | "medium" | "high" | "unknown"
    feedback_zh: str
    feedback_en: str
    deviations: list[dict]
    provider: str
    model: str
    http_status: int
    elapsed_ms: int
    raw_summary: str             # first 500 chars of raw LLM output


class LLMProvider(ABC):
    """
    All LLM implementations must subclass this.
    Only compare_images() is required for QC capability A.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def compare_images(
        self,
        standard_paths: list[str],
        production_paths: list[str],
        requirements: str = "",
        notes: str = "",
    ) -> ImageCompareResult:
        """Compare production image(s) against standard sample image(s)."""
        ...
