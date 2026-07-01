"""Provider registry — the only place that knows concrete provider classes.

Product services call :func:`get_provider_for_profile` /
:func:`get_provider` and receive a :class:`VisionLanguageModelProvider`.
They never import ``Qwen35VLProvider`` (or any vendor class) themselves, which
is what keeps product logic provider-agnostic and swappable by config.

Concrete classes are imported lazily inside the factory so that importing the
registry (and therefore product logic) never pulls in a vendor implementation.
"""
from __future__ import annotations

from typing import Callable

from src.qc_model.providers.base import VisionLanguageModelProvider
from src.qc_model.runtime_profiles import RuntimeProfile, get_runtime_profile

# Extra provider keys can be registered (e.g. mainstream adapters) at runtime.
_EXTRA_FACTORIES: dict[str, Callable[[RuntimeProfile], VisionLanguageModelProvider]] = {}


def register_provider(
    provider_key: str,
    factory: Callable[[RuntimeProfile], VisionLanguageModelProvider],
) -> None:
    """Register a mainstream-LLM/VLM adapter factory under ``provider_key``."""
    _EXTRA_FACTORIES[provider_key] = factory


def _build_default(profile: RuntimeProfile) -> VisionLanguageModelProvider:
    # Lazy import: keeps vendor class out of the import graph of product logic.
    if profile.provider == "qwen3_5_vl":
        from src.qc_model.providers.qwen3_5_vl import Qwen35VLProvider

        return Qwen35VLProvider(model=profile.model)
    raise ValueError(
        f"No provider registered for key {profile.provider!r}. "
        "Register a mainstream-LLM/VLM adapter via register_provider()."
    )


def get_provider_for_profile(profile: RuntimeProfile) -> VisionLanguageModelProvider:
    """Resolve a profile to a concrete provider instance."""
    factory = _EXTRA_FACTORIES.get(profile.provider)
    if factory is not None:
        return factory(profile)
    return _build_default(profile)


def get_provider(env: str | None = None) -> VisionLanguageModelProvider:
    """Resolve a provider for the (resolved) runtime environment."""
    return get_provider_for_profile(get_runtime_profile(env))
