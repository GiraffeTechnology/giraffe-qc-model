"""Structured observability for QC production operations (PR 29).

Emits structured log records and increments lightweight in-process metrics for
the production-safety-critical events. This is intentionally dependency-free (no
Prometheus client required): counters/latency are held in-process and can be
scraped/exported by a deployment, and every event is also logged as a structured
record for log-based observability.

``record`` never raises — observability must not break a production path.
"""
from __future__ import annotations

import logging
import threading
from collections import defaultdict

logger = logging.getLogger("qc.observability")

# Canonical event names (PR 29 §Observability).
EV_READINESS_GATE_RESULT = "readiness_gate_result"
EV_PRODUCTION_INSPECTION_RUN = "production_inspection_run"
EV_PROVIDER_LATENCY = "provider_latency"
EV_PROVIDER_ERROR = "provider_error"
EV_SCHEMA_VALIDATION_ERROR = "schema_validation_error"
EV_REVIEW_REQUIRED = "review_required"
EV_FALSE_PASS_INCIDENT = "false_pass_incident"
EV_FALSE_FAIL_INCIDENT = "false_fail_incident"
EV_HUMAN_OVERRIDE = "human_override"
EV_QUALIFICATION_RESULT = "qualification_result"

KNOWN_EVENTS = frozenset({
    EV_READINESS_GATE_RESULT, EV_PRODUCTION_INSPECTION_RUN, EV_PROVIDER_LATENCY,
    EV_PROVIDER_ERROR, EV_SCHEMA_VALIDATION_ERROR, EV_REVIEW_REQUIRED,
    EV_FALSE_PASS_INCIDENT, EV_FALSE_FAIL_INCIDENT, EV_HUMAN_OVERRIDE,
    EV_QUALIFICATION_RESULT,
})

_lock = threading.Lock()
_counters: dict[str, int] = defaultdict(int)
_latency_ms: dict[str, list[float]] = defaultdict(list)


def record(event_type: str, tenant_id: str = "", **fields) -> None:
    """Record a structured event: increment its counter and log it."""
    try:
        with _lock:
            _counters[event_type] += 1
        logger.info(
            "qc.event type=%s tenant=%s %s",
            event_type, tenant_id or "-",
            " ".join(f"{k}={v}" for k, v in fields.items()),
        )
    except Exception:  # observability must never break a production path
        pass


def observe_latency(name: str, latency_ms: float, tenant_id: str = "") -> None:
    try:
        with _lock:
            _latency_ms[name].append(float(latency_ms))
        record(EV_PROVIDER_LATENCY, tenant_id=tenant_id, name=name, latency_ms=round(float(latency_ms), 2))
    except Exception:
        pass


def snapshot() -> dict:
    """Current metric snapshot (for scraping / tests)."""
    with _lock:
        counters = dict(_counters)
        latency = {
            k: {"count": len(v), "avg_ms": (sum(v) / len(v) if v else 0.0)}
            for k, v in _latency_ms.items()
        }
    return {"counters": counters, "latency": latency}


def reset() -> None:
    with _lock:
        _counters.clear()
        _latency_ms.clear()
