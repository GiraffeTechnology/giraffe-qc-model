"""Analyzer registry with one stable lookup point for both deployment tiers."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np

from .analyzers import pearl_count, petal_segmentation, pistil_localization, rhinestone_count

Analyzer = Callable[[np.ndarray, dict[str, Any]], dict[str, Any]]

ANALYZERS: dict[str, Analyzer] = {
    "pearl_count": pearl_count,
    "petal_segmentation": petal_segmentation,
    "pistil_localization": pistil_localization,
    "rhinestone_count": rhinestone_count,
}


def analyzer_names() -> tuple[str, ...]:
    return tuple(sorted(ANALYZERS))


def get_analyzer(name: str) -> Analyzer:
    try:
        return ANALYZERS[name]
    except KeyError as exc:
        raise ValueError(f"unknown CV analyzer: {name}") from exc
