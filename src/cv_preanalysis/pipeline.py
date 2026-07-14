"""Shared orchestration, prompt framing, deviation comparison and evidence IO."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .registry import get_analyzer

CV_PROMPT_OPEN = "<CV_PREANALYSIS_JSON>"
CV_PROMPT_CLOSE = "</CV_PREANALYSIS_JSON>"


class PreanalysisError(RuntimeError):
    pass


def _load_image(image: str | Path | np.ndarray) -> np.ndarray:
    if isinstance(image, np.ndarray):
        value = image.copy()
    else:
        value = cv2.imread(str(image), cv2.IMREAD_COLOR)
    if value is None or value.size == 0 or value.ndim != 3:
        raise PreanalysisError("image could not be decoded as BGR color data")
    return value


def _parameters(config: dict[str, Any], analyzer: str) -> dict[str, Any]:
    parameters = config.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise PreanalysisError("cv_config.parameters must be an object")
    nested = parameters.get(analyzer)
    return dict(nested) if isinstance(nested, dict) else dict(parameters)


def _deviations(results: list[dict[str, Any]], expected: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not expected:
        return []
    by_name = {result["analyzer"]: result for result in results}
    deviations: list[dict[str, Any]] = []
    for feature, expected_value in sorted(expected.items()):
        analyzer_name, _, metric = feature.partition(".")
        if not metric:
            if feature in by_name:
                metric = "count"
            else:
                candidates = [r for r in results if feature in r]
                if len(candidates) != 1:
                    continue
                actual = candidates[0][feature]
                if actual != expected_value:
                    deviations.append({"feature": feature, "expected": expected_value, "actual": actual})
                continue
        result = by_name.get(analyzer_name)
        if result is None or metric not in result:
            continue
        actual = result[metric]
        if actual != expected_value:
            deviations.append({"feature": feature, "expected": expected_value, "actual": actual})
    return deviations


def run_preanalysis(
    image: str | Path | np.ndarray,
    cv_config: dict[str, Any],
    expected_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run configured analyzers deterministically; never create a verdict."""
    if not isinstance(cv_config, dict):
        raise PreanalysisError("cv_config must be an object")
    names = cv_config.get("analyzers")
    if not isinstance(names, list) or not names or not all(isinstance(name, str) for name in names):
        raise PreanalysisError("cv_config.analyzers must be a non-empty string array")
    value = _load_image(image)
    results: list[dict[str, Any]] = []
    try:
        for name in names:
            results.append(get_analyzer(name)(value, _parameters(cv_config, name)))
    except (ValueError, TypeError, cv2.error) as exc:
        raise PreanalysisError(str(exc)) from exc
    return {
        "schema_version": "1.0",
        "analyzers": results,
        "deviations": _deviations(results, expected_features),
        "verdict_effect": "informational_only",
        "accuracy_note": "accuracy unmeasured — fixture-tuned parameters are starting points",
    }


def build_prompt_block(analysis: dict[str, Any]) -> str:
    payload = json.dumps(analysis, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return (
        f"{CV_PROMPT_OPEN}\n{payload}\n{CV_PROMPT_CLOSE}\n"
        "CV pre-analysis is supporting evidence only; independently inspect the image."
    )


def write_evidence(
    directory: str | Path,
    *,
    request_id: str,
    point_code: str,
    analysis: dict[str, Any],
) -> str:
    """Persist canonical per-point JSON and return its path for audit linkage."""
    safe_request = "".join(c if c.isalnum() or c in "-_" else "_" for c in request_id)
    safe_point = "".join(c if c.isalnum() or c in "-_" else "_" for c in point_code)
    target = Path(directory) / safe_request / f"{safe_point}.cv.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(analysis, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return str(target)


def write_overlay(
    directory: str | Path,
    *,
    request_id: str,
    point_code: str,
    image: str | Path | np.ndarray,
    analysis: dict[str, Any],
) -> str:
    """Optionally render analyzer geometry; the JSON remains authoritative."""
    value = _load_image(image)
    height, width = value.shape[:2]
    color = (0, 255, 255)

    def pixel(point: dict[str, Any]) -> tuple[int, int]:
        return int(round(float(point["x"]) * width)), int(round(float(point["y"]) * height))

    for result in analysis.get("analyzers", []):
        for box in result.get("boxes", []):
            x1, y1 = pixel(box)
            x2 = int(round((float(box["x"]) + float(box["w"])) * width))
            y2 = int(round((float(box["y"]) + float(box["h"])) * height))
            cv2.rectangle(value, (x1, y1), (x2, y2), color, 1)
        box = result.get("box")
        if box:
            x1, y1 = pixel(box)
            x2 = int(round((float(box["x"]) + float(box["w"])) * width))
            y2 = int(round((float(box["y"]) + float(box["h"])) * height))
            cv2.rectangle(value, (x1, y1), (x2, y2), color, 1)
        for polygon in result.get("polygons", []):
            points = np.array([pixel(point) for point in polygon], dtype=np.int32)
            if len(points) >= 2:
                cv2.polylines(value, [points], True, color, 1)
        center = result.get("center")
        if center:
            cv2.drawMarker(value, pixel(center), color, cv2.MARKER_CROSS, 7, 1)

    safe_request = "".join(c if c.isalnum() or c in "-_" else "_" for c in request_id)
    safe_point = "".join(c if c.isalnum() or c in "-_" else "_" for c in point_code)
    target = Path(directory) / safe_request / f"{safe_point}.cv-overlay.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(target), value):
        raise PreanalysisError("overlay image could not be persisted")
    return str(target)
