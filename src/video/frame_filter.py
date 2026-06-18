"""
Tier-1: Frame differencing filter.

Compares each frame to the previous one using mean absolute pixel difference.
Frames below TIER1_DIFF_THRESHOLD are discarded as "no new content".

Cost: O(W*H) per frame — runs in ~1ms for typical 720p frames.
"""
from __future__ import annotations
import numpy as np
import cv2

from src.config import tier1_diff_threshold


def has_changed(prev_gray: np.ndarray | None, curr_gray: np.ndarray) -> tuple[bool, float]:
    """
    Return (changed, diff_score).
    changed=True means this frame differs enough to pass Tier-1.
    prev_gray=None always passes (first frame).
    Threshold is read from env at call time — no reload needed.
    """
    if prev_gray is None:
        return True, 255.0
    diff  = cv2.absdiff(prev_gray, curr_gray)
    score = float(np.mean(diff))
    return score >= tier1_diff_threshold(), score
