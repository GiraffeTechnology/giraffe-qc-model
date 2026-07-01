"""Rule-authoring provider abstraction (PR 22 §0, §6, §8).

Mirrors the learning provider pattern already used in the repo — an abstract
``QCRuleAuthoringProvider`` plus a deterministic mock, a Qwen skeleton that
fails closed (no real backend in this PR), and a lazy registry. Product logic
depends only on the abstraction, never a vendor class.

A provider returns *raw* proposal dicts (as a parsed LLM JSON response would).
The service then runs the hard validator (``validator``) which enforces the
physical-measurement guard and rejects malformed output.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from src.config import app_env
from src.qc_model.authoring.classifier import classify_fragment


@dataclass
class AuthoringFragmentInput:
    fragment_id: str
    text: str


@dataclass
class QCRuleAuthoringRequest:
    training_pack_id: str
    tenant_id: str
    fragments: list[AuthoringFragmentInput]


@dataclass
class QCRuleAuthoringResponse:
    provider: str
    model: str
    valid: bool = True
    error: Optional[str] = None
    # Each dict is a raw proposal (fragment_id + AuthoredProposal-shaped fields).
    proposals: list[dict] = field(default_factory=list)


class QCRuleAuthoringProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def author_rules(self, request: QCRuleAuthoringRequest) -> QCRuleAuthoringResponse:
        """Return raw proposal dicts. Never raise for an inference failure —
        return ``valid=False`` so the job fails closed."""
        ...


def _proposal_dict(fragment_id: str, text: str) -> dict:
    p = classify_fragment(text)
    return {
        "source_fragment_id": fragment_id,
        "source_text": text,
        "proposed_code": p.proposed_code,
        "proposed_name": p.proposed_name,
        "checkpoint_category": p.checkpoint_category,
        "ai_role": p.ai_role,
        "decision_rule": p.decision_rule,
        "review_required_conditions": p.review_required_conditions,
        "normal_visual_features": p.normal_visual_features,
        "defect_visual_features": p.defect_visual_features,
        "known_pseudo_defects": p.known_pseudo_defects,
        "questions_or_ambiguities": p.questions_or_ambiguities,
        "evidence_required": p.evidence_required,
        "severity": p.severity,
        "confidence": p.confidence,
    }


class MockRuleAuthoringProvider(QCRuleAuthoringProvider):
    """Deterministic mock. Placeholder for a real LLM (does NOT prove accuracy).

    ``valid=False`` simulates a provider/parse failure. ``raw_override`` injects
    a hostile/arbitrary raw response (used to test the guard/validator).
    """

    def __init__(
        self,
        provider_name: str = "mock_rule_authoring",
        model_name: str = "mock-authoring-v1",
        valid: bool = True,
        raw_override: Optional[list[dict]] = None,
    ) -> None:
        self._provider_name = provider_name
        self._model_name = model_name
        self._valid = valid
        self._raw_override = raw_override

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def model_name(self) -> str:
        return self._model_name

    def author_rules(self, request: QCRuleAuthoringRequest) -> QCRuleAuthoringResponse:
        if not self._valid:
            return QCRuleAuthoringResponse(
                provider=self._provider_name,
                model=self._model_name,
                valid=False,
                error="mock: malformed / unparseable LLM output",
            )
        if self._raw_override is not None:
            return QCRuleAuthoringResponse(
                provider=self._provider_name,
                model=self._model_name,
                valid=True,
                proposals=list(self._raw_override),
            )
        proposals = [_proposal_dict(f.fragment_id, f.text) for f in request.fragments]
        return QCRuleAuthoringResponse(
            provider=self._provider_name,
            model=self._model_name,
            valid=True,
            proposals=proposals,
        )


class Qwen35VLRuleAuthoringProvider(QCRuleAuthoringProvider):
    """Default server adapter skeleton — fails closed (no real backend in PR 22)."""

    def __init__(self, model: str = "qwen3.5-vl-8b-int4") -> None:
        self._model = model

    @property
    def provider_name(self) -> str:
        return "qwen3_5_vl"

    @property
    def model_name(self) -> str:
        return self._model

    def author_rules(self, request: QCRuleAuthoringRequest) -> QCRuleAuthoringResponse:
        return QCRuleAuthoringResponse(
            provider=self.provider_name,
            model=self._model,
            valid=False,
            error="qwen3.5-vl rule-authoring backend not configured in PR 22",
        )


def authoring_mock_allowed() -> bool:
    """The deterministic mock is used only when explicitly allowed (dev/test)."""
    if os.getenv("QC_AUTHORING_ALLOW_MOCK", "false").strip().lower() in ("1", "true", "yes"):
        return True
    return app_env() == "test"


def get_authoring_provider() -> QCRuleAuthoringProvider:
    """Resolve the default authoring provider. Fails closed in production."""
    if authoring_mock_allowed():
        return MockRuleAuthoringProvider()
    return Qwen35VLRuleAuthoringProvider()
