"""Production runtime-profile guards (PR 26).

Server-side VLM learning/inspection uses the **server** runtime profile
(default ``qwen3.5-vl-8b-int4``). The tablet edge profile (``tablet_mnn``,
``qwen3.5-vl-2b-mnn``) consumes confirmed rules only — it must never generate
production QC rules or run production learning.
"""
from __future__ import annotations

from src.qc_model.runtime_profiles import (
    RuntimeEnvironment,
    RuntimeProfile,
    get_runtime_profile,
    resolve_environment,
)


class TabletRuntimeNotAllowedForProduction(RuntimeError):
    """A production learning/inspection path was attempted on the tablet profile."""


def production_vlm_profile() -> RuntimeProfile:
    """The server runtime profile used for production VLM learning/inspection."""
    return get_runtime_profile(RuntimeEnvironment.SERVER.value)


def assert_server_side_runtime(env: str | None = None) -> RuntimeProfile:
    """Ensure the resolved runtime is server-side; refuse ``tablet_mnn``.

    Raises :class:`TabletRuntimeNotAllowedForProduction` when the runtime resolves
    to the tablet edge profile, so tablet runtimes cannot generate production
    QC rules or run production inspection.
    """
    if resolve_environment(env) == RuntimeEnvironment.TABLET_MNN:
        raise TabletRuntimeNotAllowedForProduction(
            "tablet_mnn runtime consumes confirmed rules only; it cannot run "
            "production learning or generate production QC rules"
        )
    return production_vlm_profile()
