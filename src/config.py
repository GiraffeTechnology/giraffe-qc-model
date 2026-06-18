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
      fake            — always use deterministic fake provider (CI / unit tests)

    Default: "fake" (safe default; never hits real model or API without opt-in)
    """
    return os.getenv("QC_ENGINE_MODE", "fake").lower()


def llm_real_calls_enabled() -> bool:
    return os.getenv("LLM_ENABLE_REAL_CALLS", "false").lower() == "true"
