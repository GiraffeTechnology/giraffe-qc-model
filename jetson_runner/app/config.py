"""Jetson runner configuration (env-driven). Headless: no interactive input."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from src.config import app_env


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, "true" if default else "false").lower() == "true"


class MockModeNotAllowedInProduction(RuntimeError):
    """Raised when JETSON_MOCK_MODE=true is requested under APP_ENV=production.

    Fail-closed: mock inference (deterministic, no real VLM) must never be
    selectable in a build/config explicitly marked production, regardless of
    what JETSON_MOCK_MODE was set to. A misconfigured deployment must refuse
    to start, not silently run mock and claim readiness.
    """


@dataclass
class RunnerConfig:
    device_id: str = field(default_factory=lambda: os.getenv("JETSON_DEVICE_ID", ""))
    # Default follows APP_ENV: true everywhere except production, so a
    # production deployment needs no special config to get the safe
    # (non-mock) behavior -- and __post_init__ still hard-rejects an explicit
    # JETSON_MOCK_MODE=true override under APP_ENV=production.
    mock_mode: bool = field(default_factory=lambda: _bool("JETSON_MOCK_MODE", app_env() != "production"))
    pairing_window_seconds: float = field(default_factory=lambda: float(os.getenv("JETSON_PAIRING_WINDOW_SECONDS", "120")))
    # LAN-only bind address for the inference endpoint (never internet-exposed, §7).
    bind_host: str = field(default_factory=lambda: os.getenv("JETSON_BIND_HOST", "0.0.0.0"))
    bind_port: int = field(default_factory=lambda: int(os.getenv("JETSON_BIND_PORT", "8600")))
    status_led_enabled: bool = field(default_factory=lambda: _bool("JETSON_STATUS_LED", False))
    # Hardware-validation escape hatch: disabled by default and restricted by
    # the HTTP layer to callers on this Jetson.
    phase1_loopback_pairing: bool = field(default_factory=lambda: _bool("JETSON_PHASE1_LOOPBACK_PAIRING", False))
    # Real adapter (llama.cpp server, see adapters/llama_cpp_adapter.py). Only
    # consulted when mock_mode is False. JetPack 5.1.x + llama.cpp per the
    # Jetson NX runtime feasibility research (Option C) -- see
    # JETSON_NX_RUNTIME_FEASIBILITY.md. The server is a separate process
    # (llama-server) reached over loopback HTTP; this avoids binding this
    # service's Python 3.11 venv to llama.cpp's Python ABI at all.
    llama_server_url: str = field(default_factory=lambda: os.getenv("JETSON_LLAMA_SERVER_URL", "http://127.0.0.1:8080"))
    llama_model_name: str = field(default_factory=lambda: os.getenv("JETSON_LLAMA_MODEL_NAME", "qwen3.5-vl-2b-int4"))
    llama_request_timeout_seconds: float = field(default_factory=lambda: float(os.getenv("JETSON_LLAMA_TIMEOUT_SECONDS", "30")))
    agent_version: str = "0.2.0"

    def __post_init__(self) -> None:
        if self.mock_mode and app_env() == "production":
            raise MockModeNotAllowedInProduction(
                "JETSON_MOCK_MODE=true is not permitted when APP_ENV=production. "
                "Set APP_ENV=test to run mock inference, or unset JETSON_MOCK_MODE "
                "(it defaults to false under APP_ENV=production) for a real "
                "deployment."
            )
