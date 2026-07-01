"""Abstract QC rule-learning provider interface (PRD §9).

The single seam between rule-learning product logic and any concrete LLM/VLM
backend. Product learning services must depend on this abstraction and never
import a Qwen-specific class directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from src.qc_model.learning.schemas import (
    QCRuleLearningRequest,
    QCRuleLearningResponse,
)


class QCRuleLearningProvider(ABC):
    """All rule-learning providers (Qwen3.5-VL, mainstream stubs, mocks) subclass this."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    @abstractmethod
    def learn_rules(self, request: QCRuleLearningRequest) -> QCRuleLearningResponse:
        """Propose structured QC rules from operator requirements + context.

        Implementations must NEVER raise to signal an inference failure — they
        return ``QCRuleLearningResponse(valid=False, ...)`` so the learning job
        fails closed (status ``failed`` + supervisor review). If an
        implementation does raise, the service converts it to a fail-closed
        failed job.
        """
        ...
