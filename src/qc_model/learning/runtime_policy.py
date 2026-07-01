"""Learning runtime profile policy (PRD §4).

Rule learning defaults to the **server** profile (`qwen3.5-vl-8b-int4`). The
`tablet_mnn` profile is for edge-side execution of confirmed rules, NOT for
learning. The deprecated desktop edge-profile name must never be usable.

Hard rules enforced here:
1. Default learning runtime is `server`.
2. `tablet_mnn` must not be the default learning runtime, and an explicit
   attempt to learn on it is rejected (supervisor review required) — never a
   silent tablet learning run.
3. Any runtime that is not a known runtime environment is rejected outright
   (this covers the deprecated desktop edge-profile name, which is not a valid
   environment and must not silently fall back to server).
"""
from __future__ import annotations

from dataclasses import dataclass

from src.qc_model.runtime_profiles import (
    RuntimeEnvironment,
    RuntimeProfile,
    get_runtime_profile,
)

DEFAULT_LEARNING_ENVIRONMENT = RuntimeEnvironment.SERVER

# The only runtime environments that exist in the product.
_KNOWN_RUNTIMES = {e.value for e in RuntimeEnvironment}


class LearningRuntimeError(ValueError):
    """Raised when an invalid/forbidden learning runtime is requested."""


@dataclass(frozen=True)
class RuntimePolicyDecision:
    allowed: bool
    profile: RuntimeProfile | None
    reason: str = ""


def resolve_learning_profile(requested: str | None = None) -> RuntimeProfile:
    """Return the runtime profile for learning, defaulting to server.

    Raises LearningRuntimeError for any runtime that is not a known runtime
    environment (this includes the deprecated desktop edge-profile name), so an
    unknown value never silently falls back to server.
    """
    if requested is None:
        return get_runtime_profile(DEFAULT_LEARNING_ENVIRONMENT.value)
    if requested not in _KNOWN_RUNTIMES:
        raise LearningRuntimeError(
            f"Runtime {requested!r} is not a known runtime environment. "
            "The edge profile is 'tablet_mnn'; learning runs on 'server'."
        )
    return get_runtime_profile(requested)


def evaluate_learning_runtime(requested: str | None = None) -> RuntimePolicyDecision:
    """Decide whether a requested learning runtime is allowed.

    - ``None`` / ``server`` -> allowed (server profile).
    - ``tablet_mnn`` -> NOT allowed for learning; the caller must route the job
      to a supervisor-review-required state.
    - unknown runtime (incl. the deprecated desktop edge-profile name) -> hard
      rejection.
    """
    if requested is not None and requested not in _KNOWN_RUNTIMES:
        return RuntimePolicyDecision(
            allowed=False, profile=None, reason="forbidden_or_unknown_runtime"
        )

    profile = resolve_learning_profile(requested)

    if profile.environment == RuntimeEnvironment.TABLET_MNN:
        return RuntimePolicyDecision(
            allowed=False,
            profile=profile,
            reason="tablet_mnn_not_allowed_for_learning_requires_supervisor_review",
        )

    return RuntimePolicyDecision(allowed=True, profile=profile, reason="server_learning_profile")
