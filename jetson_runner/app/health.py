"""Jetson health/readiness reporting (§6.1) — surfaced on the Pad, the only screen.

Mock mode returns deterministic healthy values so CI is stable; a real Xavier NX
build would read tegrastats / jetson_stats here. There is no local display: this
data is what the Pad shows so an operator never plugs a monitor into the Jetson.
"""
from __future__ import annotations

from src.qc_model.jetson import constants as C


def collect_health(*, mock: bool = True, model_loaded: bool = True, last_inference_latency_ms: int | None = None) -> dict:
    if mock:
        return {
            "service_up": True,
            "model_loaded": model_loaded,
            "temperature_c": 61.5,
            "throttling": False,
            "disk_free_percent": 72.0,
            "last_inference_latency_ms": last_inference_latency_ms,
            "readiness_state": C.READY if model_loaded else C.CONNECTING,
            # Explicit per docs/api-contracts/jetson-runner-api.md §4 — the
            # Pad must be able to tell mock health from real health, not just
            # infer it from other fields.
            "mock": True,
        }
    try:  # pragma: no cover - real hardware path, not exercised in CI
        from jtop import jtop  # type: ignore

        with jtop() as jt:
            stats = jt.stats
            return {
                "service_up": True,
                "model_loaded": model_loaded,
                "temperature_c": stats.get("Temp CPU"),
                "throttling": bool(stats.get("jetson_clocks") is False),
                "disk_free_percent": None,
                "last_inference_latency_ms": last_inference_latency_ms,
                "readiness_state": C.READY if model_loaded else C.CONNECTING,
                "mock": False,
            }
    except Exception:
        return {"service_up": True, "model_loaded": model_loaded, "readiness_state": C.CONNECTING, "mock": False}
