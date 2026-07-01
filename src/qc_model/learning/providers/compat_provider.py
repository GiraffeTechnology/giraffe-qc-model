"""Mainstream LLM/VLM rule-learning adapter stub.

Proves the learning engine is not Qwen-bound: a mainstream provider satisfies
the same :class:`QCRuleLearningProvider` interface. It wraps a vendor-neutral
``call_fn`` that returns a fully-formed :class:`QCRuleLearningResponse`.
"""
from __future__ import annotations

from typing import Callable

from src.qc_model.learning.providers.base import QCRuleLearningProvider
from src.qc_model.learning.schemas import (
    QCRuleLearningRequest,
    QCRuleLearningResponse,
)


class MainstreamRuleLearningAdapter(QCRuleLearningProvider):
    """Adapter for any mainstream LLM/VLM exposed through ``call_fn``."""

    def __init__(
        self,
        call_fn: Callable[[QCRuleLearningRequest], QCRuleLearningResponse],
        provider_name: str = "mainstream_rule_learning",
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

    def learn_rules(self, request: QCRuleLearningRequest) -> QCRuleLearningResponse:
        try:
            return self._call_fn(request)
        except Exception as exc:  # fail closed, never raise into product logic
            return QCRuleLearningResponse(
                provider=self._provider_name,
                model=self._model_name,
                runtime_profile=request.runtime_profile,
                valid=False,
                error=f"{type(exc).__name__}: {exc}",
            )
