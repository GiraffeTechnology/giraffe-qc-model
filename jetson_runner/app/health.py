"""Truthful Xavier health telemetry for the Administrator runner."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _device_health() -> dict:
    """Return measured values or explicit unknowns; never healthy fixtures."""
    total = free = None
    try:
        usage = shutil.disk_usage("/")
        total, free = usage.total, usage.free
    except OSError:
        pass

    temperature = None
    throttling = None
    try:  # pragma: no cover - Xavier-only optional telemetry
        from jtop import jtop  # type: ignore

        with jtop() as jetson:
            temperature = jetson.stats.get("Temp CPU")
            clocks = jetson.stats.get("jetson_clocks")
            throttling = clocks is False if clocks is not None else None
    except Exception:
        pass

    if throttling is True:
        thermal_state = "throttled"
    elif temperature is None:
        thermal_state = "unknown"
    elif temperature >= 75:
        thermal_state = "warm"
    else:
        thermal_state = "normal"
    return {
        "temperature_c": temperature,
        "thermal_state": thermal_state,
        "throttling": throttling,
        "disk_free_bytes": free,
        "disk_total_bytes": total,
    }


def collect_admin_health(
    *,
    runner_id: str,
    agent_version: str,
    adapter_mode: str,
    model_name: str,
    model_revision: str,
    model_loaded: bool,
    loaded_at: str | None,
    credentials_configured: bool,
    last_recognition: dict | None,
    hardware_validation_status: str,
    hardware_validation_evidence_ref: str | None,
) -> dict:
    ready = model_loaded and credentials_configured
    return {
        "schema_version": "2.0",
        "runner_id": runner_id,
        "agent_version": agent_version,
        "observed_at": utc_now(),
        "readiness": "ready" if ready else "not_ready",
        "service_up": True,
        "runtime": {
            "engine": "mnn",
            "adapter_mode": adapter_mode,
            "model_name": model_name,
            "model_revision": model_revision,
            "model_loaded": model_loaded,
            "loaded_at": loaded_at if model_loaded else None,
        },
        # Package readiness means the deterministic software stage is loaded;
        # it is not a device-specific accuracy or latency claim.
        "cv_pipeline": {"status": "ready", "package_version": "1.0"},
        "device": _device_health(),
        "last_recognition": last_recognition,
        "hardware_validation": {
            "status": hardware_validation_status,
            "evidence_ref": hardware_validation_evidence_ref,
        },
        "mock": adapter_mode == "mock",
    }
