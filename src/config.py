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
