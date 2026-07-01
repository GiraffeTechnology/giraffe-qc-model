"""Default Qwen3.5-VL rule-learning adapter (skeleton).

This is the *default* provider for the server learning profile
(`qwen3.5-vl-8b-int4`), but it is just one implementation of
:class:`QCRuleLearningProvider`. Product logic never imports this class
directly — it goes through :mod:`src.qc_model.learning.providers.registry`.

Phase 2A boundary: this adapter performs NO real inference and does NOT certify
qwen3.5-vl accuracy. With no real backend configured it fails closed
(``valid=False``), which makes the learning job fail closed to supervisor
review. Real inference wiring is a later phase.
"""
from __future__ import annotations

from src.qc_model.learning.providers.base import QCRuleLearningProvider
from src.qc_model.learning.schemas import (
    QCRuleLearningRequest,
    QCRuleLearningResponse,
)


class Qwen35VLRuleLearningProvider(QCRuleLearningProvider):
    """Default Qwen3.5-VL rule-learning adapter for the server profile."""

    def __init__(self, model: str = "qwen3.5-vl-8b-int4") -> None:
        self._model = model

    @property
    def provider_name(self) -> str:
        return "qwen3_5_vl"

    @property
    def model_name(self) -> str:
        return self._model

    def learn_rules(self, request: QCRuleLearningRequest) -> QCRuleLearningResponse:
        # Phase 2A: no real backend is wired. Fail closed so no proposals are
        # fabricated and the job requires supervisor review.
        return QCRuleLearningResponse(
            provider=self.provider_name,
            model=self._model,
            runtime_profile=request.runtime_profile,
            valid=False,
            error="qwen3.5-vl rule-learning backend not configured in Phase 2A",
        )
