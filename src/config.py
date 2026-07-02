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


def fake_provider_allowed() -> bool:
    # In production, override env vars can never re-enable a fake adapter.
    if app_env() == "production":
        return False
    return app_env() == "test" or os.getenv("QC_ALLOW_TEST_ADAPTER", "false").lower() == "true"
