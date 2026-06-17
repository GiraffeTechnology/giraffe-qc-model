#!/usr/bin/env python
"""Generate two synthetic test MP4 videos using OpenCV VideoWriter."""
import os, sys, struct, zlib
import numpy as np
import cv2
from pathlib import Path

OUT = Path("tests/fixtures/videos")
OUT.mkdir(parents=True, exist_ok=True)
FPS = 10
W, H = 320, 240


def gray_background() -> np.ndarray:
    """Conveyor-belt style gray background — clearly NOT the red product."""
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    frame[:] = (180, 180, 180)   # BGR gray
    return frame


def frame_product_closeup(defect: bool = False) -> np.ndarray:
    """
    Close-up shot of the product — fills most of frame (simulates camera
    positioned directly above product for QC inspection).
    The product is red (matches sample), with optional black dot defect.
    """
    frame = np.zeros((H, W, 3), dtype=np.uint8)
    frame[:] = (30, 30, 220)   # BGR ≈ red (220, 30, 30) — product fills frame
    if defect:
        # Black dot defect in center region
        cx, cy = W // 2, H // 2
        frame[cy-20:cy+20, cx-20:cx+20] = (0, 0, 0)
    return frame


def write_video(path: str, frames: list[np.ndarray], fps: int = FPS) -> None:
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, fps, (W, H))
    for f in frames:
        writer.write(f)
    writer.release()


# ── Video 1: product appears for QC inspection ────────────────────────────
# 2s conveyor (gray, no product) → 1s product close-up (TARGET) → 2s conveyor
frames_target = (
    [gray_background()] * 20 +
    [frame_product_closeup(defect=True)] * 10 +   # red product with defect
    [gray_background()] * 20
)
write_video(str(OUT / "video_with_target.mp4"), frames_target)
print(f"video_with_target.mp4  : {len(frames_target)} frames @ {FPS}fps")
print(f"  Frames 0-19  : gray conveyor background (no target)")
print(f"  Frames 20-29 : red product close-up with defect (TARGET)")
print(f"  Frames 30-49 : gray conveyor background (no target)")

# ── Video 2: only conveyor — no product ever ──────────────────────────────
frames_no_target = [gray_background() for _ in range(50)]
write_video(str(OUT / "video_no_target.mp4"), frames_no_target)
print(f"video_no_target.mp4    : {len(frames_no_target)} frames @ {FPS}fps (gray conveyor only)")

print("\nTest videos generated in tests/fixtures/videos/")
