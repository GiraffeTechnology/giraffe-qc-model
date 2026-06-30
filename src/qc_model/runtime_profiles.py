"""Dual default Qwen3.5-VL runtime profiles + environment-based selection.

The product has **two** default runtime profiles, selected by execution
environment — not one generic ``qwen3.5-vl`` model:

    desktop_pc_mnn -> qwen3.5-vl-2b-mnn   (default desktop/PC MNN profile)
    server         -> qwen3.5-vl-8b-int4  (default server profile)

Both default to the ``qwen3_5_vl`` provider, but the architecture stays
provider-compatible: a profile's ``provider`` is just a registry key, and the
registry can resolve mainstream LLM/VLM adapters too.

This module is product configuration only. It does **not** drive the physical
Android Pad MNN runtime (``apps/android-qc``), which keeps its own model
wiring. See ``docs/QC_MODEL_PHASE1_VISUAL_QC.md`` for the documented mismatch
between the existing Android model name and these product-default profiles.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum


class RuntimeEnvironment(str, Enum):
    """Execution environment that selects a runtime profile."""

    DESKTOP_PC_MNN = "desktop_pc_mnn"
    SERVER = "server"


@dataclass(frozen=True)
class RuntimeProfile:
    """One default runtime profile binding env -> provider + model."""

    environment: RuntimeEnvironment
    provider: str
    model: str
    role: str

    def to_config(self) -> dict[str, str]:
        return {"provider": self.provider, "model": self.model, "role": self.role}


# Product default profiles. Keyed by environment value to mirror the PRD's
# ``default_runtime_profiles`` config block exactly.
DEFAULT_RUNTIME_PROFILES: dict[RuntimeEnvironment, RuntimeProfile] = {
    RuntimeEnvironment.DESKTOP_PC_MNN: RuntimeProfile(
        environment=RuntimeEnvironment.DESKTOP_PC_MNN,
        provider="qwen3_5_vl",
        model="qwen3.5-vl-2b-mnn",
        role="default_desktop_pc_mnn_visual_reasoning_profile",
    ),
    RuntimeEnvironment.SERVER: RuntimeProfile(
        environment=RuntimeEnvironment.SERVER,
        provider="qwen3_5_vl",
        model="qwen3.5-vl-8b-int4",
        role="default_server_visual_reasoning_profile",
    ),
}

# The provider abstraction is compatible with mainstream LLM/VLM providers.
MAINSTREAM_LLM_VLM_ADAPTERS_SUPPORTED = True


def resolve_environment(env: str | None = None) -> RuntimeEnvironment:
    """Resolve the runtime environment from an explicit arg or env var.

    ``QC_VISION_RUNTIME_ENV`` selects the profile. Unknown / unset values
    fall back to the server profile (the safer, larger default).
    """
    raw = env or os.environ.get("QC_VISION_RUNTIME_ENV", RuntimeEnvironment.SERVER.value)
    try:
        return RuntimeEnvironment(raw)
    except ValueError:
        return RuntimeEnvironment.SERVER


def get_runtime_profile(env: str | None = None) -> RuntimeProfile:
    """Return the default runtime profile for the (resolved) environment."""
    return DEFAULT_RUNTIME_PROFILES[resolve_environment(env)]


def default_runtime_profiles_config() -> dict:
    """Return the product-default config block (mirrors PRD §3.3)."""
    return {
        "default_runtime_profiles": {
            env.value: profile.to_config()
            for env, profile in DEFAULT_RUNTIME_PROFILES.items()
        },
        "provider_compatibility": {
            "mainstream_llm_vlm_adapters_supported": MAINSTREAM_LLM_VLM_ADAPTERS_SUPPORTED,
        },
    }
