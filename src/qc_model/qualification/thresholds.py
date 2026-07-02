"""L3 qualification thresholds (PR 27).

Conservative, environment-configurable defaults. False pass is critical
(default max false-pass rate = 0). Tests may lower the sample minimums via env
to exercise the passing path without large fixtures, but must still verify that
exceeding the false-pass threshold blocks L3.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class QualificationThresholds:
    max_false_pass_rate: float
    max_false_fail_rate: float
    min_samples_per_point: int
    min_defect_samples_per_point: int
    min_boundary_samples_per_point: int

    def to_dict(self) -> dict:
        return {
            "max_false_pass_rate": self.max_false_pass_rate,
            "max_false_fail_rate": self.max_false_fail_rate,
            "min_samples_per_point": self.min_samples_per_point,
            "min_defect_samples_per_point": self.min_defect_samples_per_point,
            "min_boundary_samples_per_point": self.min_boundary_samples_per_point,
        }


def get_l3_thresholds() -> QualificationThresholds:
    return QualificationThresholds(
        max_false_pass_rate=_env_float("QC_MAX_FALSE_PASS_RATE_L3", 0.0),
        max_false_fail_rate=_env_float("QC_MAX_FALSE_FAIL_RATE_L3", 0.05),
        min_samples_per_point=_env_int("QC_MIN_QUALIFICATION_SAMPLES_PER_POINT", 30),
        min_defect_samples_per_point=_env_int("QC_MIN_DEFECT_SAMPLES_PER_POINT", 10),
        min_boundary_samples_per_point=_env_int("QC_MIN_BOUNDARY_SAMPLES_PER_POINT", 5),
    )
