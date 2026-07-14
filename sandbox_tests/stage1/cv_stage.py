"""Deterministic sandbox CV preprocessing using the shared WS8 package."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2

from src.cv_preanalysis import run_preanalysis


def run_cv_stage(image_path: str | Path, cv_config: dict[str, Any]) -> dict[str, Any]:
    source = Path(image_path)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError("sandbox input image could not be decoded")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return {
        "input_width_px": int(image.shape[1]),
        "input_height_px": int(image.shape[0]),
        "brightness_mean": round(float(gray.mean()), 4),
        "sharpness_laplacian_variance": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 4),
        "preanalysis": run_preanalysis(image, cv_config),
        "verdict_effect": "informational_only",
    }
