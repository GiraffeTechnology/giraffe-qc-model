"""Seed-data-driven QC simulation runner.

The runner intentionally does not call Pad, MNN, DashScope, or production QWEN
provider routing. It evaluates machine-readable simulation labels and produces
point-level accuracy reports for QC policy validation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DATASET_ROOT = Path("data/qc_simulation/artificial_jewelry_flower_brooch")

DETECTION_POINTS: tuple[dict[str, str], ...] = (
    {
        "code": "center_alignment",
        "name": "Center alignment",
        "severity": "major",
        "description": "Flower heart / central stamen cluster is centered relative to the four petals.",
    },
    {
        "code": "rhinestone_count",
        "name": "Rhinestone count",
        "severity": "critical",
        "description": "All required rhinestones / crystals in the stamen cluster are present.",
    },
    {
        "code": "pearl_count",
        "name": "Pearl count",
        "severity": "critical",
        "description": "Required pearl beads are present and count matches the standard image.",
    },
    {
        "code": "pearl_surface_integrity",
        "name": "Pearl surface integrity",
        "severity": "major",
        "description": "Pearl beads have no visible cracks, chips, or surface fissures.",
    },
    {
        "code": "petal_integrity",
        "name": "Petal integrity",
        "severity": "major",
        "description": "Petals have no cracks, chips, broken edges, or missing pieces.",
    },
    {
        "code": "incidental_abnormality",
        "name": "Incidental abnormality",
        "severity": "minor",
        "description": "Visible abnormalities are reported even if not explicitly requested.",
    },
)

REQUIRED_POINT_CODES = tuple(point["code"] for point in DETECTION_POINTS)
VALID_RESULTS = {"pass", "fail", "review_required"}


@dataclass(frozen=True)
class SimulationOutcome:
    sample_id: str
    expected_final_result: str
    actual_final_result: str
    expected_checkpoint_results: dict[str, str]
    actual_checkpoint_results: dict[str, str]
    reason: str | None = None

    @property
    def final_result_matches(self) -> bool:
        return self.expected_final_result == self.actual_final_result


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} is not valid JSONL") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            rows.append(row)
    return rows


def build_sku_standard() -> dict[str, Any]:
    return {
        "sku_id": "artificial_jewelry_flower_brooch_001",
        "sku_name": "Artificial jewelry flower brooch / hair clip",
        "detection_points": list(DETECTION_POINTS),
        "standard_photo_id": "seed_standard_001",
    }


def validate_checkpoint_results(checkpoints: list[dict[str, Any]]) -> dict[str, str]:
    if not checkpoints:
        return {}

    results: dict[str, str] = {}
    for checkpoint in checkpoints:
        code = checkpoint.get("code")
        result = checkpoint.get("result")
        if code not in REQUIRED_POINT_CODES:
            raise ValueError(f"Unknown point_code: {code!r}")
        if result not in VALID_RESULTS:
            raise ValueError(f"Invalid checkpoint result for {code!r}: {result!r}")
        if code in results:
            raise ValueError(f"Duplicate checkpoint result for point_code: {code!r}")
        results[code] = result
    return results


def final_result_from_checkpoints(checkpoints: dict[str, str]) -> tuple[str, str | None]:
    if not checkpoints:
        return "review_required", "empty_model_output"

    missing = [code for code in REQUIRED_POINT_CODES if code not in checkpoints]
    if missing:
        return "review_required", f"missing_checkpoint_results:{','.join(missing)}"

    unknown = [code for code in checkpoints if code not in REQUIRED_POINT_CODES]
    if unknown:
        raise ValueError(f"Unknown point_code: {unknown[0]!r}")

    if any(result == "fail" for result in checkpoints.values()):
        return "fail", "one_or_more_checkpoint_failures"
    if any(result == "review_required" for result in checkpoints.values()):
        return "review_required", "one_or_more_checkpoints_need_review"
    if all(result == "pass" for result in checkpoints.values()):
        return "pass", None
    return "review_required", "incomplete_checkpoint_evaluation"


def validate_label(label: dict[str, Any]) -> None:
    required_fields = {
        "sample_id",
        "sku_id",
        "image_path",
        "based_on_seed",
        "is_synthetic",
        "expected_final_result",
        "defects",
        "expected_checkpoint_results",
    }
    missing = sorted(required_fields - set(label))
    if missing:
        raise ValueError(f"Label {label.get('sample_id', '<unknown>')} missing fields: {missing}")
    if label["expected_final_result"] not in VALID_RESULTS:
        raise ValueError(f"Invalid expected_final_result: {label['expected_final_result']!r}")
    checkpoints = validate_checkpoint_results(label["expected_checkpoint_results"])
    final_result, reason = final_result_from_checkpoints(checkpoints)
    if final_result != label["expected_final_result"]:
        raise ValueError(
            f"Label {label['sample_id']} expected_final_result={label['expected_final_result']!r} "
            f"does not match checkpoint-derived result={final_result!r} ({reason})"
        )


def simulate_sample(label: dict[str, Any], model_output: list[dict[str, Any]] | None = None) -> SimulationOutcome:
    validate_label(label)
    expected_checkpoints = validate_checkpoint_results(label["expected_checkpoint_results"])
    if model_output is None:
        actual_checkpoints = dict(expected_checkpoints)
    else:
        actual_checkpoints = validate_checkpoint_results(model_output)

    actual_final, reason = final_result_from_checkpoints(actual_checkpoints)
    critical_defects = [
        defect for defect in label.get("defects", [])
        if defect.get("severity") == "critical"
    ]
    if critical_defects and actual_final == "pass":
        actual_final = "fail"
        reason = "critical_defect_cannot_pass"

    return SimulationOutcome(
        sample_id=label["sample_id"],
        expected_final_result=label["expected_final_result"],
        actual_final_result=actual_final,
        expected_checkpoint_results=expected_checkpoints,
        actual_checkpoint_results=actual_checkpoints,
        reason=reason,
    )


def simulate_model_payload(label: dict[str, Any], payload: dict[str, Any] | None) -> SimulationOutcome:
    """Evaluate a model-like payload while ignoring model-provided overall_result.

    This mirrors the simulation policy: final verdicts are derived only from
    required point-level checkpoint results. A contradictory model-level
    overall_result cannot turn a failing checkpoint into a pass.
    """
    if not payload or not payload.get("items"):
        return simulate_sample(label, model_output=[])
    if not isinstance(payload["items"], list):
        return simulate_sample(label, model_output=[])

    model_output = []
    for item in payload["items"]:
        if not isinstance(item, dict):
            continue
        model_output.append(
            {
                "code": item.get("code") or item.get("point_code") or item.get("qc_point_code"),
                "result": item.get("result"),
            }
        )
    return simulate_sample(label, model_output=model_output)


def run_simulation(dataset_root: Path = DATASET_ROOT) -> dict[str, Any]:
    seed_metadata = load_jsonl(dataset_root / "seed" / "source_metadata.jsonl")
    synthetic_metadata = load_jsonl(dataset_root / "synthetic" / "synthetic_metadata.jsonl")
    real_metadata_path = dataset_root / "real" / "real_metadata.jsonl"
    real_metadata = load_jsonl(real_metadata_path) if real_metadata_path.exists() else []
    labels = load_jsonl(dataset_root / "labels" / "expected_results.jsonl")

    metadata_by_sample = {
        row["sample_id"]: row for row in synthetic_metadata + real_metadata
    }
    outcomes: list[SimulationOutcome] = []
    for label in labels:
        metadata = metadata_by_sample.get(label["sample_id"])
        if metadata is None:
            raise ValueError(f"Missing sample metadata for sample_id={label['sample_id']!r}")
        image_path = Path(label["image_path"])
        if not image_path.exists():
            raise FileNotFoundError(image_path)
        if metadata.get("is_synthetic") is not label.get("is_synthetic"):
            raise ValueError(
                f"Sample {label['sample_id']} has inconsistent is_synthetic metadata"
            )
        outcomes.append(simulate_sample(label))

    report = build_report(outcomes, labels, seed_metadata, synthetic_metadata, real_metadata)
    reports_dir = dataset_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "simulation_report.json"
    report["report_path"] = str(report_path)
    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    return report


def build_report(
    outcomes: list[SimulationOutcome],
    labels: list[dict[str, Any]],
    seed_metadata: list[dict[str, Any]],
    synthetic_metadata: list[dict[str, Any]],
    real_metadata: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    real_metadata = real_metadata or []
    total = len(outcomes)
    final_matches = sum(1 for outcome in outcomes if outcome.final_result_matches)
    point_total = 0
    point_matches = 0
    false_passes: list[str] = []
    false_fails: list[str] = []
    missed_defects: list[dict[str, str]] = []
    unexpected_incidental_findings: list[dict[str, str]] = []
    samples_failed_by_reason: dict[str, list[str]] = {}

    labels_by_sample = {label["sample_id"]: label for label in labels}
    per_defect_counts: dict[str, dict[str, int]] = {}

    for outcome in outcomes:
        label = labels_by_sample[outcome.sample_id]
        expected_defect_codes = [
            defect["code"] for defect in label.get("defects", [])
            if defect.get("code") != "none"
        ] or ["pass"]
        for defect_code in expected_defect_codes:
            bucket = per_defect_counts.setdefault(defect_code, {"total": 0, "matched": 0})
            bucket["total"] += 1
            if outcome.final_result_matches:
                bucket["matched"] += 1

        if outcome.actual_final_result == "pass" and outcome.expected_final_result != "pass":
            false_passes.append(outcome.sample_id)
        if outcome.actual_final_result == "fail" and outcome.expected_final_result == "pass":
            false_fails.append(outcome.sample_id)
        if outcome.reason:
            samples_failed_by_reason.setdefault(outcome.reason, []).append(outcome.sample_id)

        for code, expected_result in outcome.expected_checkpoint_results.items():
            point_total += 1
            actual_result = outcome.actual_checkpoint_results.get(code)
            if actual_result == expected_result:
                point_matches += 1
            elif expected_result == "fail" and actual_result != "fail":
                missed_defects.append({"sample_id": outcome.sample_id, "point_code": code})

        actual_incidental = outcome.actual_checkpoint_results.get("incidental_abnormality")
        expected_incidental = outcome.expected_checkpoint_results.get("incidental_abnormality")
        if actual_incidental == "fail" and expected_incidental != "fail":
            unexpected_incidental_findings.append(
                {"sample_id": outcome.sample_id, "point_code": "incidental_abnormality"}
            )

    return {
        "sku_standard": build_sku_standard(),
        "generated_at": seed_metadata[0].get("captured_at") if seed_metadata else None,
        "seed_image_count": len(seed_metadata),
        "synthetic_sample_count": len(synthetic_metadata),
        "real_production_sample_count": len(real_metadata),
        "total_samples": total,
        "final_result_accuracy": final_matches / total if total else 0.0,
        "point_level_accuracy": point_matches / point_total if point_total else 0.0,
        "false_pass_count": len(false_passes),
        "false_fail_count": len(false_fails),
        "review_required_count": sum(1 for outcome in outcomes if outcome.actual_final_result == "review_required"),
        "per_defect_type_accuracy": {
            code: counts["matched"] / counts["total"] if counts["total"] else 0.0
            for code, counts in sorted(per_defect_counts.items())
        },
        "missed_defects": missed_defects,
        "unexpected_incidental_findings": unexpected_incidental_findings,
        "samples_failed_by_reason": samples_failed_by_reason,
        "false_pass_samples": false_passes,
        "false_fail_samples": false_fails,
    }


def main() -> None:
    report = run_simulation()
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
