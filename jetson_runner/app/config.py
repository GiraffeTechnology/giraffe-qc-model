"""Jetson runner configuration (env-driven). Headless: no interactive input."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, "true" if default else "false").lower() == "true"


@dataclass
class RunnerConfig:
    device_id: str = field(default_factory=lambda: os.getenv("JETSON_DEVICE_ID", ""))
    mock_mode: bool = field(default_factory=lambda: _bool("JETSON_MOCK_MODE", True))
    pairing_window_seconds: float = field(default_factory=lambda: float(os.getenv("JETSON_PAIRING_WINDOW_SECONDS", "120")))
    # LAN-only bind address for the inference endpoint (never internet-exposed, §7).
    bind_host: str = field(default_factory=lambda: os.getenv("JETSON_BIND_HOST", "0.0.0.0"))
    bind_port: int = field(default_factory=lambda: int(os.getenv("JETSON_BIND_PORT", "8600")))
    status_led_enabled: bool = field(default_factory=lambda: _bool("JETSON_STATUS_LED", False))
    agent_version: str = "0.1.0"
