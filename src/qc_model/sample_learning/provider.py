"""VLM sample-learning provider (PR 23 §0, §6).

Mirrors the existing provider pattern (mock + qwen skeleton + fail-closed gate)
used across the QC model — it does not introduce a new integration mechanism.
The mock produces deterministic per-sample observations so the pipeline is
testable without a live VLM; it proves workflow, not real visual accuracy.

A provider returns *raw* observation dicts (as a parsed VLM JSON response
would); the service validates and persists them. On failure it returns
``valid=False`` so the job fails closed.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from src.config import app_env
from src.qc_model.sample_learning.types import (
    SAMPLE_TYPE_TO_FEATURE,
    SampleType,
)


@dataclass
class SampleInput:
    sample_id: str
    image_reference: str = ""


@dataclass
class SampleLearningRequest:
    training_pack_id: str
    tenant_id: str
    detection_point_code: str
    sample_type: str
    samples: list[SampleInput]


@dataclass
class SampleLearningResponse:
    provider: str
    model: str
    valid: bool = True
    error: Optional[str] = None
    observations: list[dict] = field(default_factory=list)


class SampleLearningProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def learn_samples(self, request: SampleLearningRequest) -> SampleLearningResponse:
        """Return raw per-sample observation dicts. Never raise for an inference
        failure — return ``valid=False`` so the job fails closed."""
        ...


def _observation_for(sample: SampleInput, sample_type: str, detection_point_code: str) -> dict:
    stype = SampleType(sample_type)
    feature_type = SAMPLE_TYPE_TO_FEATURE[stype].value
    base = {
        "source_sample_id": sample.sample_id,
        "image_reference": sample.image_reference,
        "detection_point_code": detection_point_code,
        "feature_type": feature_type,
        "evidence_region": None,  # mock has no bbox
        "confidence": 0.6,
        "uncertainty": "mock deterministic observation; not real visual accuracy",
        "requires_human_review": True,
        "normal_visual_features": [],
        "acceptable_variations": [],
        "defect_visual_features": [],
        "known_pseudo_defects": [],
        "capture_artifact_risks": [],
        "evidence_required": [f"reference image {sample.image_reference or sample.sample_id}"],
        "review_required_conditions": [],
    }
    if stype == SampleType.REFERENCE:
        base["normal_visual_features"] = ["normal structure consistent with the reference sample"]
        base["rule_implication"] = "defines the normal appearance baseline"
    elif stype == SampleType.POSITIVE:
        base["acceptable_variations"] = ["acceptable variation within the qualified range"]
        base["rule_implication"] = "expands the acceptable-variation envelope"
    elif stype == SampleType.DEFECT:
        base["defect_visual_features"] = ["visible defect signature distinct from normal material"]
        base["rule_implication"] = "defines a defect signature to fail on"
    elif stype == SampleType.BOUNDARY:
        base["acceptable_variations"] = ["borderline-but-acceptable appearance"]
        base["known_pseudo_defects"] = ["reflection", "shadow", "angle-induced pseudo-defect"]
        base["review_required_conditions"] = ["ambiguous boundary appearance"]
        base["rule_implication"] = "teaches review_required instead of guessing near the boundary"
    elif stype == SampleType.CAPTURE_ARTIFACT:
        base["capture_artifact_risks"] = ["glare", "overexposure", "motion blur"]
        base["rule_implication"] = "flags capture-artifact risks that mimic defects"
    return base


class MockSampleLearningProvider(SampleLearningProvider):
    """Deterministic mock. Placeholder for a real VLM (proves workflow only)."""

    def __init__(
        self,
        provider_name: str = "mock_sample_learning",
        model_name: str = "mock-vlm-sample-v1",
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

    def learn_samples(self, request: SampleLearningRequest) -> SampleLearningResponse:
        if not self._valid:
            return SampleLearningResponse(
                provider=self._provider_name,
                model=self._model_name,
                valid=False,
                error="mock: malformed / unparseable VLM output",
            )
        if self._raw_override is not None:
            return SampleLearningResponse(
                provider=self._provider_name, model=self._model_name, valid=True,
                observations=list(self._raw_override),
            )
        obs = [
            _observation_for(s, request.sample_type, request.detection_point_code)
            for s in request.samples
        ]
        return SampleLearningResponse(
            provider=self._provider_name, model=self._model_name, valid=True, observations=obs
        )


class Qwen35VLSampleLearningProvider(SampleLearningProvider):
    """Default server adapter skeleton — fails closed (no real backend yet).

    Production sample learning uses the **server** runtime profile
    (``qwen3.5-vl-8b-int4`` by default), never the ``tablet_mnn`` edge profile.
    """

    def __init__(self, model: str | None = None) -> None:
        if model is None:
            from src.qc_model.runtime_profiles import RuntimeEnvironment, get_runtime_profile

            model = get_runtime_profile(RuntimeEnvironment.SERVER.value).model
        self._model = model

    @property
    def provider_name(self) -> str:
        return "qwen3_5_vl"

    @property
    def model_name(self) -> str:
        return self._model

    def learn_samples(self, request: SampleLearningRequest) -> SampleLearningResponse:
        return SampleLearningResponse(
            provider=self.provider_name, model=self._model, valid=False,
            error="qwen3.5-vl sample-learning backend not configured in PR 23",
        )


def sample_learning_mock_allowed() -> bool:
    # In production, the override env var can never re-enable mock sample learning.
    if app_env() == "production":
        return False
    if os.getenv("QC_SAMPLE_LEARNING_ALLOW_MOCK", "false").strip().lower() in ("1", "true", "yes"):
        return True
    return app_env() == "test"


def get_sample_learning_provider() -> SampleLearningProvider:
    if sample_learning_mock_allowed():
        return MockSampleLearningProvider()
    return Qwen35VLSampleLearningProvider()
