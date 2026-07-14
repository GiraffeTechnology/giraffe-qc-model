"""Semantic comparison for native-baseline and QEMU-aarch64 CV probe output."""
from __future__ import annotations

from typing import Any


def _tolerance(path: str) -> float:
    if path.endswith("brightness_mean"):
        return 0.01
    if path.endswith("sharpness_laplacian_variance"):
        return 0.1
    return 0.001


def compare_values(left: Any, right: Any, path: str = "cv_result") -> list[str]:
    differences: list[str] = []
    if isinstance(left, bool) or isinstance(right, bool):
        if left is not right:
            differences.append(f"{path}: {left!r} != {right!r}")
    elif isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if abs(float(left) - float(right)) > _tolerance(path):
            differences.append(f"{path}: {left!r} != {right!r}")
    elif isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            differences.append(
                f"{path}: key sets differ ({sorted(left)} != {sorted(right)})"
            )
        for key in sorted(set(left) & set(right)):
            differences.extend(compare_values(left[key], right[key], f"{path}.{key}"))
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            differences.append(f"{path}: list lengths differ ({len(left)} != {len(right)})")
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            differences.extend(
                compare_values(left_item, right_item, f"{path}[{index}]")
            )
    elif left != right:
        differences.append(f"{path}: {left!r} != {right!r}")
    return differences


def compare_probes(
    baseline: dict[str, Any], arm64: dict[str, Any]
) -> list[dict[str, Any]]:
    baseline_cases = {case["case_id"]: case for case in baseline["cases"]}
    arm64_cases = {case["case_id"]: case for case in arm64["cases"]}
    if set(baseline_cases) != set(arm64_cases):
        raise ValueError("baseline and aarch64 case sets differ")
    results: list[dict[str, Any]] = []
    for case_id in sorted(baseline_cases):
        native = baseline_cases[case_id]
        emulated = arm64_cases[case_id]
        differences = []
        if native["input_sha256"] != emulated["input_sha256"]:
            differences.append("fixture sha256 differs")
        differences.extend(compare_values(native["cv_result"], emulated["cv_result"]))
        results.append(
            {
                "case_id": case_id,
                "category": native["category"],
                "input_ref": native["input_ref"],
                "input_sha256": native["input_sha256"],
                "native_cv_result": native["cv_result"],
                "arm64_cv_result": emulated["cv_result"],
                "differences": differences,
                "passed": not differences,
            }
        )
    return results
