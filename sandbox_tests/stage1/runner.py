"""Execute Stage 1: local fixture capture → CV → sandbox VLM → strict verdict."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from sandbox_tests.common import (
    SANDBOX_DECLARATION,
    SandboxConfig,
    forbidden_server_values,
    load_env_file,
)
from sandbox_tests.reporting import REPORT_SCHEMA_VERSION, write_reports
from sandbox_tests.stage1.architecture import (
    ArchitectureVerificationError,
    architecture_ready,
    load_runtime_env_file,
    verify_architecture,
)
from sandbox_tests.stage1.client import SandboxInferenceError, SandboxVLMClient
from sandbox_tests.stage1.cv_stage import run_cv_stage
from sandbox_tests.stage1.parser import (
    StrictOutputError,
    fail_closed_result,
    parse_strict_sandbox_output,
)


ROOT = Path(__file__).parents[2]
MOCK_CAPTURE_LABEL = (
    "NON-PRODUCTION MOCK — repository fixture simulates capture input; "
    "no camera or external hardware was used."
)
MOCK_OUTPUT_LABEL = (
    "NON-PRODUCTION MOCK — malformed model output fixture is deliberate fault injection."
)
MOCK_TIMEOUT_LABEL = (
    "NON-PRODUCTION MOCK — timeout is deliberately injected before transport."
)


def load_cases(path: str | Path) -> list[dict[str, Any]]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, list) or not value:
        raise ValueError("stage1 cases must be a non-empty array")
    seen = set()
    allowed_categories = {
        "visual_defect",
        "physical_measurement",
        "rule_verification",
        "subjective_judgment",
    }
    for case in value:
        required = {
            "case_id",
            "case_type",
            "category",
            "qc_point_id",
            "name",
            "input_ref",
            "criterion",
            "expected_behavior",
            "expected_verdict",
            "cv_config",
        }
        missing = sorted(required - case.keys())
        if missing:
            raise ValueError(f"case missing fields: {missing}")
        if case["case_id"] in seen:
            raise ValueError(f"duplicate case id: {case['case_id']}")
        seen.add(case["case_id"])
        if case["category"] not in allowed_categories:
            raise ValueError(f"unsupported category: {case['category']}")
        if case["expected_verdict"] not in {"pass", "reject"}:
            raise ValueError("expected_verdict must be pass or reject")
        input_path = (ROOT / case["input_ref"]).resolve()
        if ROOT.resolve() not in input_path.parents or not input_path.is_file():
            raise ValueError(f"case input is missing or outside repository: {case['case_id']}")
        fixture_ref = case.get("model_output_fixture")
        if fixture_ref:
            fixture_path = (ROOT / fixture_ref).resolve()
            if ROOT.resolve() not in fixture_path.parents or not fixture_path.is_file():
                raise ValueError(f"model output fixture missing: {case['case_id']}")
    return value


def execute_case(
    case: dict[str, Any],
    *,
    client: SandboxVLMClient,
) -> dict[str, Any]:
    overall_started = time.perf_counter()
    input_path = ROOT / case["input_ref"]
    cv_started = time.perf_counter()
    cv_result = run_cv_stage(input_path, case["cv_config"])
    cv_ms = _elapsed(cv_started)
    inference_started = time.perf_counter()
    raw = ""
    parser_input = ""
    mock_flags = [MOCK_CAPTURE_LABEL]
    error_reason = ""
    try:
        if case["case_type"] == "forced_timeout":
            mock_flags.append(MOCK_TIMEOUT_LABEL)
            raise SandboxInferenceError("model_timeout")
        if case["case_type"] == "malformed_fixture":
            mock_flags.append(MOCK_OUTPUT_LABEL)
            raw = (ROOT / case["model_output_fixture"]).read_text(encoding="utf-8")
            parser_input = raw
        elif case["case_type"] == "real_inference":
            response = client.infer(case=case, image_path=input_path, cv_result=cv_result)
            raw = response.raw_output
            parser_input = response.parser_input
        else:
            raise ValueError(f"unknown case_type: {case['case_type']}")
    except SandboxInferenceError as exc:
        error_reason = str(exc)
    inference_ms = _elapsed(inference_started)
    parse_started = time.perf_counter()
    if error_reason:
        parsed = fail_closed_result(error_reason)
    else:
        try:
            parsed = parse_strict_sandbox_output(
                parser_input,
                expected_qc_point_ids=[case["qc_point_id"]],
            )
        except StrictOutputError as exc:
            parsed = fail_closed_result(str(exc))
    parse_ms = _elapsed(parse_started)
    notes = list(parsed.anomaly_notes)
    if parsed.think_tags_stripped:
        notes.append("think_tags_stripped")
    passed = parsed.verdict == case["expected_verdict"]
    if not passed:
        notes.append(
            f"expected_{case['expected_verdict']}_observed_{parsed.verdict}"
        )
    return {
        "case_id": case["case_id"],
        "case_type": case["case_type"],
        "category": case["category"],
        "input_ref": case["input_ref"],
        "raw_model_output": raw,
        "parsed_result": parsed.parsed_result,
        "verdict": parsed.verdict,
        "timing_ms": {
            "cv": cv_ms,
            "inference": inference_ms,
            "parse": parse_ms,
            "total": _elapsed(overall_started),
        },
        "passed": passed,
        "anomaly_notes": notes,
        "mock_flags": mock_flags,
        "think_tags_stripped": parsed.think_tags_stripped,
    }


def build_report(
    config: SandboxConfig,
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
    architecture: dict[str, object] | None = None,
) -> dict[str, Any]:
    categories = {
        category: {
            "positive": sum(r["case_id"].startswith(f"{category}-positive") for r in results),
            "anomalous": sum(r["case_id"].startswith(f"{category}-anomalous") for r in results),
        }
        for category in {
            "visual_defect",
            "physical_measurement",
            "rule_verification",
            "subjective_judgment",
        }
    }
    forced = [r for r in results if r["case_type"] != "real_inference"]
    real = [r for r in results if r["case_type"] == "real_inference"]
    acceptance = {
        "sandbox_architecture_checkout_data_and_mysql_ready": architecture_ready(architecture),
        "end_to_end_no_blocking_errors": bool(real) and all(r["passed"] for r in real),
        "four_categories_positive_and_anomalous_executed": all(
            counts["positive"] >= 1 and counts["anomalous"] >= 1
            for counts in categories.values()
        ),
        "fail_closed_model_anomaly_timeout_and_format_error": len(forced) >= 3
        and all(r["verdict"] == "reject" and r["passed"] for r in forced),
        "real_output_think_sanitization_observed": any(r["think_tags_stripped"] for r in real),
        "all_simulated_elements_labeled": all(
            all(flag.startswith("NON-PRODUCTION MOCK —") for flag in r["mock_flags"])
            for r in results
        ),
        "all_cases_passed": all(r["passed"] for r in results),
    }
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "stage": 1,
        "status": "passed" if all(acceptance.values()) else "failed",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment_declaration": SANDBOX_DECLARATION,
        "model_delta_note": config.model_delta_note,
        "runtime": {
            "api_style": config.api_style,
            "model": config.model,
            "server": "SANDBOX_QC_SERVER",
            "server_value_redacted": True,
        },
        "architecture": architecture or {"ready": False, "error": "not_verified"},
        "summary": {
            "case_count": len(results),
            "passed_case_count": sum(r["passed"] for r in results),
            "failed_case_count": sum(not r["passed"] for r in results),
            "real_inference_case_count": len(real),
            "fault_injection_case_count": len(forced),
            "category_coverage": categories,
        },
        "acceptance": acceptance,
        "cases": results,
    }


def assert_report_has_no_server_address(report: dict[str, Any], config: SandboxConfig) -> None:
    serialized = json.dumps(report, ensure_ascii=False)
    forbidden = forbidden_server_values(config.server)
    if any(value and value in serialized for value in forbidden):
        raise ValueError("sandbox server address leak refused; report was not written")


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default="sandbox.env")
    parser.add_argument("--runtime-env", default=".env.stage1.local")
    parser.add_argument("--cases", default="sandbox_tests/stage1/cases.json")
    parser.add_argument("--report", default="sandbox_tests/reports/stage1_report.json")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    if args.validate_only:
        print(f"validated {len(cases)} Stage 1 cases; no inference executed")
        return 0
    load_env_file(args.env_file)
    load_runtime_env_file(args.runtime_env)
    config = SandboxConfig.from_environment()
    try:
        architecture = verify_architecture(ROOT)
    except ArchitectureVerificationError as exc:
        architecture = {"ready": False, "error": str(exc)}
    client = SandboxVLMClient(config)
    try:
        results = [execute_case(case, client=client) for case in cases]
    finally:
        client.close()
    report = build_report(config, cases, results, architecture)
    assert_report_has_no_server_address(report, config)
    json_path, markdown_path = write_reports(report, args.report)
    print(f"wrote {json_path} and {markdown_path}; status={report['status']}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
