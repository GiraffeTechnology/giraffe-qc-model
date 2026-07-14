"""Jetson runner configuration (env-driven). Headless: no interactive input."""
from __future__ import annotations

import json
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


def _inference_mode() -> str:
    """Resolve the explicit Administrator-runner inference mode.

    Architecture v2 never defaults to mock. ``JETSON_MOCK_MODE`` remains a
    temporary compatibility input for existing CI/deployment manifests, but it
    is only honored when it is explicitly present.
    """
    explicit = os.getenv("XAVIER_INFERENCE_MODE")
    if explicit:
        return explicit.strip().lower()
    legacy = os.getenv("JETSON_MOCK_MODE")
    if legacy is not None:
        return "mock" if legacy.lower() == "true" else "real"
    return "real"


def _admin_credentials() -> dict:
    raw = os.getenv("XAVIER_ADMIN_CREDENTIALS_JSON", "{}")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("XAVIER_ADMIN_CREDENTIALS_JSON must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("XAVIER_ADMIN_CREDENTIALS_JSON must be a JSON object")
    return value


@dataclass
class RunnerConfig:
    device_id: str = field(default_factory=lambda: os.getenv("JETSON_DEVICE_ID", ""))
    inference_mode: str = field(default_factory=_inference_mode)
    # Constructor compatibility for existing tests/deployments. New code sets
    # XAVIER_INFERENCE_MODE. When supplied directly, this explicit value wins.
    mock_mode: bool | None = None
    pairing_window_seconds: float = field(default_factory=lambda: float(os.getenv("JETSON_PAIRING_WINDOW_SECONDS", "120")))
    # LAN-only bind address for the inference endpoint (never internet-exposed, §7).
    bind_host: str = field(default_factory=lambda: os.getenv("JETSON_BIND_HOST", "0.0.0.0"))
    bind_port: int = field(default_factory=lambda: int(os.getenv("JETSON_BIND_PORT", "8600")))
    status_led_enabled: bool = field(default_factory=lambda: _bool("JETSON_STATUS_LED", False))
    # Hardware-validation escape hatch: disabled by default and restricted by
    # the HTTP layer to callers on this Jetson.
    phase1_loopback_pairing: bool = field(default_factory=lambda: _bool("JETSON_PHASE1_LOOPBACK_PAIRING", False))
    # Administrator-side Architecture v2 runtime via a native MNN bridge.
    # qwen3-vl-4b is a replaceable deployment default, not product identity.
    mnn_bridge_library: str = field(default_factory=lambda: os.getenv(
        "XAVIER_MNN_BRIDGE_LIBRARY", "/opt/giraffe/lib/libgiraffe_mnn_bridge.so"
    ))
    mnn_model_dir: str = field(default_factory=lambda: os.getenv(
        "XAVIER_MNN_MODEL_DIR", "/opt/giraffe/models/qwen3-vl-4b-mnn"
    ))
    mnn_model_name: str = field(default_factory=lambda: os.getenv(
        "XAVIER_MNN_MODEL_NAME", "qwen3-vl-4b"
    ))
    admin_credentials: dict = field(default_factory=_admin_credentials)
    auth_clock_skew_seconds: int = field(default_factory=lambda: int(os.getenv(
        "XAVIER_AUTH_CLOCK_SKEW_SECONDS", "300"
    )))
    auth_nonce_ttl_seconds: int = field(default_factory=lambda: int(os.getenv(
        "XAVIER_AUTH_NONCE_TTL_SECONDS", "600"
    )))
    max_request_bytes: int = field(default_factory=lambda: int(os.getenv(
        "XAVIER_MAX_REQUEST_BYTES", str(20 * 1024 * 1024)
    )))
    hardware_validation_status: str = field(default_factory=lambda: os.getenv(
        "XAVIER_HARDWARE_VALIDATION_STATUS", "not_run"
    ))
    hardware_validation_evidence_ref: str | None = field(default_factory=lambda: os.getenv(
        "XAVIER_HARDWARE_VALIDATION_EVIDENCE_REF"
    ))
    agent_version: str = "0.3.0"

    def __post_init__(self) -> None:
        if self.mock_mode is not None:
            self.inference_mode = "mock" if self.mock_mode else "real"
        if self.inference_mode not in {"real", "mock"}:
            raise ValueError("XAVIER_INFERENCE_MODE must be 'real' or 'mock'")
        if self.hardware_validation_status not in {"not_run", "passed", "failed"}:
            raise ValueError("XAVIER_HARDWARE_VALIDATION_STATUS is invalid")
        if self.hardware_validation_status == "passed" and not self.hardware_validation_evidence_ref:
            raise ValueError("passed hardware validation requires an evidence reference")
        self.mock_mode = self.inference_mode == "mock"
        if self.mock_mode and app_env() == "production":
            raise MockModeNotAllowedInProduction(
                "XAVIER_INFERENCE_MODE=mock is not permitted when APP_ENV=production. "
                "Use APP_ENV=test for labeled mock tests or select the real MNN adapter."
            )
