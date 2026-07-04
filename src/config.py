"""
Central runtime configuration.

All values are read at call time (not import time), so monkeypatch/env
changes work in tests without importlib.reload().
"""
from __future__ import annotations
import os
from pathlib import Path


def sample_store_dir() -> Path:
    return Path(os.getenv("SAMPLE_STORE_DIR", "data/samples"))


def capture_dir() -> Path:
    return Path(os.getenv("CAPTURE_DIR", "data/captures"))


def video_sample_fps() -> float:
    return float(os.getenv("VIDEO_SAMPLE_FPS", "2"))


def tier1_diff_threshold() -> float:
    return float(os.getenv("TIER1_DIFF_THRESHOLD", "5"))


def local_prefilter_threshold() -> float:
    return float(os.getenv("LOCAL_PREFILTER_THRESHOLD", "0.25"))


def bundle_signing_secret() -> str:
    """Shared secret used to sign/verify bundle manifests (§7.3).

    The publisher (studio) and the bundle-management/verify path must agree on
    this value. Read at call time so tests can set it per-case. A non-empty
    default keeps dev/test self-contained; production must set BUNDLE_SIGNING_SECRET.
    """
    return os.getenv("BUNDLE_SIGNING_SECRET", "dev-bundle-signing-secret")


def qc_engine_mode() -> str:
    """Return the active QC engine mode.

    Values:
      cloud_qwen_dev  — temporary dev/testing mode; calls DashScope cloud API
                        requires LLM_ENABLE_REAL_CALLS=true + DASHSCOPE_API_KEY
      on_device_first — final production mode (Android MNN primary, cloud fallback)
      backend_proxy   — cloud API is the primary path (explicit override)
      fake            — deterministic fake provider; test harness only

    Default: "on_device_first" (production-safe; never returns fake pass)
    """
    return os.getenv("QC_ENGINE_MODE", "on_device_first").lower()


def llm_real_calls_enabled() -> bool:
    return os.getenv("LLM_ENABLE_REAL_CALLS", "false").lower() == "true"


def app_env() -> str:
    return os.getenv("APP_ENV", "production").lower()


# ── Edge CV (hot-pluggable co-processor) ─────────────────────────────────────
# All read at call time so tests can toggle per-case. The feature is optional:
# when EDGE_CV_ENABLED is false the rest of the system behaves exactly as before.


def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, "true" if default else "false").lower() == "true"


def edge_cv_enabled() -> bool:
    return _env_bool("EDGE_CV_ENABLED", True)


def edge_cv_hotplug_enabled() -> bool:
    return _env_bool("EDGE_CV_HOTPLUG_ENABLED", True)


def edge_cv_mock_enabled() -> bool:
    return _env_bool("EDGE_CV_MOCK_ENABLED", True)


def edge_cv_cpu_fallback() -> bool:
    return _env_bool("EDGE_CV_CPU_FALLBACK", True)


def edge_cv_heartbeat_interval_seconds() -> int:
    return int(os.getenv("EDGE_CV_HEARTBEAT_INTERVAL_SECONDS", "10"))


def edge_cv_heartbeat_ttl_seconds() -> int:
    return int(os.getenv("EDGE_CV_HEARTBEAT_TTL_SECONDS", "35"))


def edge_cv_job_lease_seconds() -> int:
    return int(os.getenv("EDGE_CV_JOB_LEASE_SECONDS", "60"))


def edge_cv_job_poll_interval_seconds() -> int:
    return int(os.getenv("EDGE_CV_JOB_POLL_INTERVAL_SECONDS", "3"))


def edge_cv_max_retries() -> int:
    return int(os.getenv("EDGE_CV_MAX_RETRIES", "2"))


def edge_cv_default_device_type() -> str:
    return os.getenv("EDGE_CV_DEFAULT_DEVICE_TYPE", "jetson_nano_2gb")


def edge_cv_recapture_cooldown_seconds() -> float:
    """Live-capture dedup window: suppress re-capturing the same tracked object.

    Device-local hint returned to the agent (Live-Capture Auto-Lock addendum).
    """
    return float(os.getenv("EDGE_CV_RECAPTURE_COOLDOWN_SECONDS", "5"))


def fake_provider_allowed() -> bool:
    # In production, override env vars can never re-enable a fake adapter.
    if app_env() == "production":
        return False
    return app_env() == "test" or os.getenv("QC_ALLOW_TEST_ADAPTER", "false").lower() == "true"
