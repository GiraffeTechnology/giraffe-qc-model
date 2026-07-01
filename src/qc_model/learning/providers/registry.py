"""Rule-learning provider registry — the only place that knows vendor classes.

Product learning services call :func:`get_learning_provider` and receive a
:class:`QCRuleLearningProvider`. They never import a vendor class themselves,
which keeps product logic provider-agnostic and swappable by config.
"""
from __future__ import annotations

from typing import Callable

from src.qc_model.learning.providers.base import QCRuleLearningProvider
from src.qc_model.runtime_profiles import RuntimeProfile

_EXTRA_FACTORIES: dict[str, Callable[[RuntimeProfile], QCRuleLearningProvider]] = {}


def register_learning_provider(
    provider_key: str,
    factory: Callable[[RuntimeProfile], QCRuleLearningProvider],
) -> None:
    """Register a mainstream-LLM/VLM learning adapter factory."""
    _EXTRA_FACTORIES[provider_key] = factory


def get_learning_provider_for_profile(profile: RuntimeProfile) -> QCRuleLearningProvider:
    """Resolve a runtime profile to a concrete learning provider instance."""
    factory = _EXTRA_FACTORIES.get(profile.provider)
    if factory is not None:
        return factory(profile)

    # Lazy import keeps the vendor class out of product logic's import graph.
    if profile.provider == "qwen3_5_vl":
        from src.qc_model.learning.providers.qwen3_5_vl import (
            Qwen35VLRuleLearningProvider,
        )

        return Qwen35VLRuleLearningProvider(model=profile.model)

    raise ValueError(
        f"No learning provider registered for key {profile.provider!r}. "
        "Register a mainstream-LLM/VLM adapter via register_learning_provider()."
    )
