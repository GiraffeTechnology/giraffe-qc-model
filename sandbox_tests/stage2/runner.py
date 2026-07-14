"""Build the Stage 2 report from external-drive, QEMU ARM64, CV, and UI evidence."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sandbox_tests.common import SANDBOX_DECLARATION
from sandbox_tests.reporting import REPORT_SCHEMA_VERSION, write_reports
from sandbox_tests.stage2.comparison import compare_probes
from sandbox_tests.stage2.gate import Stage2DecisionRequired, Stage2Gate


MODEL_DELTA_NOTE = (
    "Stage 2 CV/UI simulation requires no real LLM/VLM call. Sandbox and "
    "production model selections remain replaceable configured defaults, not "
    "Giraffe product identity or ecosystem dependencies. Qwen is one configured "
    "default, not a required product ecosystem. This report contains no "
    "model-quality evidence."
)

MOCK_CAPTURE_LABEL = (
    "NON-PRODUCTION MOCK — repository fixture simulates capture input; no camera "
    "or external hardware was used."
)
MOCK_INFERENCE_LABEL = (
    "NON-PRODUCTION MOCK — Stage 2 stops after standalone CV; no LLM/VLM was invoked."
)
MOCK_UI_LABEL = (
    "NON-PRODUCTION MOCK — UI state is driven by Stage 2 simulation evidence."
)
REQUIRED_UI_CASES = {
    "simulator-ready",
    "simulated-capture",
    "cv-success",
    "cv-anomaly",
    "simulator-unavailable",
    "refresh-retry",
}


def build_blocked_report(reason: str) -> dict[str, object]:
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "stage": 2,
        "status": "blocked",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment_declaration": SANDBOX_DECLARATION,
        "model_delta_note": MODEL_DELTA_NOTE,
        "summary": {
            "case_count": 0,
            "passed_case_count": 0,
            "failed_case_count": 0,
            "simulation_method_selected": False,
            "external_volume_selected": False,
            "ui_validation_required": True,
            "blocking_reason": reason,
        },
        "acceptance": {
            "simulation_method_recorded": False,
            "external_drive_rw_stable": False,
            "cv_module_complete_without_arch_or_dependency_error": False,
            "stage1_stage2_difference_list_complete": False,
            "simulation_limitations_recorded": False,
            "ui_validation_complete": False,
        },
        "cases": [],
    }


def _read_json(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"evidence must be a JSON object: {Path(path).name}")
    return value


def _cv_report_cases(comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": f"stage2-{item['case_id']}",
            "case_type": "qemu_aarch64_cv_comparison",
            "category": item["category"],
            "input_ref": item["input_ref"],
            "raw_model_output": "",
            "parsed_result": {
                "input_sha256": item["input_sha256"],
                "native_cv_result": item["native_cv_result"],
                "arm64_cv_result": item["arm64_cv_result"],
                "within_declared_tolerance": item["passed"],
            },
            "verdict": "pass" if item["passed"] else "reject",
            "timing_ms": {"cv": 0.0, "inference": 0.0, "parse": 0.0, "total": 0.0},
            "passed": item["passed"],
            "anomaly_notes": item["differences"],
            "mock_flags": [MOCK_CAPTURE_LABEL, MOCK_INFERENCE_LABEL],
        }
        for item in comparisons
    ]


def _ui_report_cases(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    cases = manifest.get("cases", [])
    if not isinstance(cases, list):
        raise ValueError("UI evidence cases must be an array")
    results = []
    for item in cases:
        case_id = str(item.get("case_id", ""))
        results.append(
            {
                "case_id": f"stage2-ui-{case_id}",
                "case_type": "android_ui_validation",
                "category": "subjective_judgment",
                "input_ref": str(item.get("screenshot", "")),
                "raw_model_output": "",
                "parsed_result": item.get("state_payload", {}),
                "verdict": "pass" if item.get("passed") else "reject",
                "timing_ms": {
                    "cv": 0.0,
                    "inference": 0.0,
                    "parse": 0.0,
                    "total": 0.0,
                },
                "passed": bool(item.get("passed")),
                "anomaly_notes": list(item.get("anomaly_notes", [])),
                "mock_flags": [MOCK_UI_LABEL, MOCK_INFERENCE_LABEL],
            }
        )
    return results


def build_completed_report(
    *,
    gate: Stage2Gate,
    baseline: dict[str, Any],
    arm64: dict[str, Any],
    drive: dict[str, Any],
    ui: dict[str, Any],
    difference_list_complete: bool,
    limitations_recorded: bool,
) -> dict[str, Any]:
    comparisons = compare_probes(baseline, arm64)
    cv_cases = _cv_report_cases(comparisons)
    ui_cases = _ui_report_cases(ui)
    all_cases = cv_cases + ui_cases
    ui_ids = {
        case["case_id"].removeprefix("stage2-ui-") for case in ui_cases if case["passed"]
    }
    machine = str(arm64.get("runtime", {}).get("machine", "")).lower()
    arm64_runtime = machine in {"aarch64", "arm64"}
    volume_matches = drive.get("volume_name") == gate.external_drive_root.parts[2]
    drive_ok = all(
        bool(drive.get(key))
        for key in ("write_fsync_completed", "read_back_completed", "sha256_matches")
    ) and volume_matches
    cv_ok = bool(cv_cases) and arm64_runtime and all(case["passed"] for case in cv_cases)
    ui_ok = REQUIRED_UI_CASES <= ui_ids and all(case["passed"] for case in ui_cases)
    acceptance = {
        "simulation_method_recorded": gate.method == "qemu_aarch64",
        "external_drive_rw_stable": drive_ok,
        "cv_module_complete_without_arch_or_dependency_error": cv_ok,
        "stage1_stage2_difference_list_complete": difference_list_complete,
        "simulation_limitations_recorded": limitations_recorded,
        "ui_validation_complete": ui_ok,
        "all_cases_passed": bool(all_cases) and all(case["passed"] for case in all_cases),
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "stage": 2,
        "status": "passed" if all(acceptance.values()) else "failed",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment_declaration": SANDBOX_DECLARATION,
        "model_delta_note": MODEL_DELTA_NOTE,
        "runtime": {
            "simulation_method": gate.method,
            "external_volume": gate.external_drive_root.parts[2],
            "external_backed_stage2_root": gate.external_drive_root.name,
            "native": baseline.get("runtime", {}),
            "qemu_guest": arm64.get("runtime", {}),
            "model_invoked": False,
            "camera_connected": False,
            "jetson_hardware_connected": False,
        },
        "drive_evidence": drive,
        "ui_evidence": {
            "platform": ui.get("platform"),
            "build_variant": ui.get("build_variant"),
            "case_count": len(ui_cases),
            "required_case_ids": sorted(REQUIRED_UI_CASES),
        },
        "summary": {
            "case_count": len(all_cases),
            "passed_case_count": sum(case["passed"] for case in all_cases),
            "failed_case_count": sum(not case["passed"] for case in all_cases),
            "cv_case_count": len(cv_cases),
            "ui_case_count": len(ui_cases),
            "simulation_method": gate.method,
            "arm64_guest_verified": arm64_runtime,
            "model_call_count": 0,
        },
        "acceptance": acceptance,
        "cases": all_cases,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        default="sandbox_tests/reports/stage2_report.json",
    )
    parser.add_argument(
        "--baseline-probe",
        default="sandbox_tests/reports/evidence/stage2/native-cv-probe.json",
    )
    parser.add_argument(
        "--arm64-probe",
        default="sandbox_tests/reports/evidence/stage2/arm64-cv-probe.json",
    )
    parser.add_argument(
        "--drive-evidence",
        default="sandbox_tests/reports/evidence/stage2/drive-probe.json",
    )
    parser.add_argument(
        "--ui-manifest",
        default="sandbox_tests/reports/evidence/stage2/ui-manifest.json",
    )
    args = parser.parse_args(argv)
    try:
        gate = Stage2Gate.from_environment()
    except Stage2DecisionRequired as exc:
        json_path, markdown_path = write_reports(build_blocked_report(str(exc)), args.report)
        print(f"wrote {json_path} and {markdown_path}; status=blocked")
        return 2
    difference_text = (Path(__file__).parent / "DIFFERENCE_LIST.md").read_text(
        encoding="utf-8"
    )
    decision_text = (Path(__file__).parent / "DECISION_RECORD.md").read_text(
        encoding="utf-8"
    )
    report = build_completed_report(
        gate=gate,
        baseline=_read_json(args.baseline_probe),
        arm64=_read_json(args.arm64_probe),
        drive=_read_json(args.drive_evidence),
        ui=_read_json(args.ui_manifest),
        difference_list_complete="Status: **completed**" in difference_text,
        limitations_recorded=all(
            term in decision_text for term in ("GPU", "CUDA", "camera", "power", "thermal")
        ),
    )
    json_path, markdown_path = write_reports(report, args.report)
    print(f"wrote {json_path} and {markdown_path}; status={report['status']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
