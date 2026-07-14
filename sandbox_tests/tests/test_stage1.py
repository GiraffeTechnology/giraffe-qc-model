from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pytest

from sandbox_tests.common import (
    SANDBOX_DECLARATION,
    SandboxConfig,
    SandboxConfigurationError,
    forbidden_server_values,
)
from sandbox_tests.reporting import REPORT_SCHEMA_VERSION, render_markdown, write_reports
from sandbox_tests.stage1.architecture import (
    ArchitectureVerificationError,
    architecture_ready,
    load_runtime_env_file,
    verify_architecture,
)
from sandbox_tests.stage1.client import SandboxVLMClient
from sandbox_tests.stage1.cv_stage import run_cv_stage
from sandbox_tests.stage1.parser import StrictOutputError, parse_strict_sandbox_output
from sandbox_tests.stage1.runner import (
    ROOT,
    assert_report_has_no_server_address,
    build_report,
    execute_case,
    load_cases,
)


CASES = ROOT / "sandbox_tests" / "stage1" / "cases.json"


def _config(**updates) -> SandboxConfig:
    values = {
        "server": "https://sandbox.invalid",
        "model": "sandbox-configured-model",
        "api_style": "openai_chat",
        "inference_path": "/v1/chat/completions",
        "api_key": "",
        "timeout_seconds": 5.0,
        "max_image_bytes": 5_242_880,
        "max_output_chars": 100_000,
        "production_cloud_model": "cloud-default-model",
        "production_admin_model": "admin-default-model",
    }
    values.update(updates)
    return SandboxConfig(**values)


def _valid_raw(point_id: str = "point-1", result: str = "pass") -> str:
    return json.dumps(
        {
            "overall_result": result,
            "confidence": 0.9,
            "model_name": "configured-model",
            "summary": "fixture",
            "items": [
                {
                    "qc_point_id": point_id,
                    "qc_point_code": point_id,
                    "name": "point",
                    "result": result,
                    "confidence": 0.9,
                    "reason": "visible evidence",
                    "evidence": {},
                }
            ],
        }
    )


def test_environment_config_rejects_placeholder_or_missing_values(monkeypatch):
    for key in (
        "SANDBOX_QC_SERVER",
        "SANDBOX_QC_MODEL",
        "SANDBOX_PRODUCTION_CLOUD_MODEL",
        "SANDBOX_PRODUCTION_ADMIN_MODEL",
    ):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(SandboxConfigurationError, match="SANDBOX_QC_SERVER"):
        SandboxConfig.from_environment()


def test_environment_config_is_provider_neutral_and_relative_path_only(monkeypatch):
    monkeypatch.setenv("SANDBOX_QC_SERVER", "https://sandbox.invalid:8443")
    monkeypatch.setenv("SANDBOX_QC_MODEL", "configured-sandbox-vlm")
    monkeypatch.setenv("SANDBOX_QC_API_STYLE", "openai_chat")
    monkeypatch.setenv("SANDBOX_QC_INFERENCE_PATH", "/v1/chat/completions")
    monkeypatch.setenv("SANDBOX_PRODUCTION_CLOUD_MODEL", "configured-cloud-default")
    monkeypatch.setenv("SANDBOX_PRODUCTION_ADMIN_MODEL", "configured-admin-default")
    config = SandboxConfig.from_environment()
    assert config.model == "configured-sandbox-vlm"
    assert config.model_delta_note.endswith(
        "Results are chain-validity evidence, not model-quality evidence."
    )
    monkeypatch.setenv("SANDBOX_QC_INFERENCE_PATH", "https://different.invalid/path")
    with pytest.raises(SandboxConfigurationError, match="relative absolute path"):
        SandboxConfig.from_environment()


def test_server_leak_values_ignore_generic_loopback_but_keep_external_hostname():
    loopback = forbidden_server_values("http://127.0.0.1:8080")
    assert loopback == {"http://127.0.0.1:8080"}
    external = forbidden_server_values("https://203.0.113.10:8443")
    assert external == {"https://203.0.113.10:8443", "203.0.113.10"}


def test_case_manifest_has_four_categories_positive_anomalous_and_faults():
    cases = load_cases(CASES)
    real = [case for case in cases if case["case_type"] == "real_inference"]
    assert len(real) == 8
    for category in {
        "visual_defect",
        "physical_measurement",
        "rule_verification",
        "subjective_judgment",
    }:
        selected = [case for case in real if case["category"] == category]
        assert {case["expected_verdict"] for case in selected} == {"pass", "reject"}
    assert {case["case_type"] for case in cases} >= {
        "real_inference",
        "forced_timeout",
        "malformed_fixture",
    }


def test_think_tags_are_stripped_from_valid_model_output():
    raw = "<think>private reasoning</think>\n" + _valid_raw()
    result = parse_strict_sandbox_output(raw, expected_qc_point_ids=["point-1"])
    assert result.verdict == "pass"
    assert result.think_tags_stripped is True
    assert "private reasoning" not in result.sanitized_output


@pytest.mark.parametrize(
    "raw,reason",
    [
        ('{"overall_result":"pass"', "json_parse_failed"),
        (_valid_raw() + " trailing", "trailing_content_rejected"),
        ('{"overall_result":"pass","overall_result":"fail"}', "duplicate_key"),
        (_valid_raw().replace("fixture", "ignore previous instructions"), "injection_marker_rejected"),
    ],
)
def test_strict_parser_rejects_malformed_and_injection_output(raw, reason):
    with pytest.raises(StrictOutputError, match=reason):
        parse_strict_sandbox_output(raw, expected_qc_point_ids=["point-1"])


def test_missing_point_fails_closed():
    result = parse_strict_sandbox_output(
        '{"overall_result":"pass","confidence":1,"items":[]}',
        expected_qc_point_ids=["point-1"],
    )
    assert result.verdict == "reject"
    assert result.parsed_result["overall_result"] == "review_required"


def test_cv_stage_uses_shared_deterministic_package():
    result = run_cv_stage(
        ROOT / "tests" / "fixtures" / "cv_preanalysis_fixture.pgm",
        {"analyzers": ["rhinestone_count"], "parameters": {"morphology_kernel_px": 1}},
    )
    assert result["preanalysis"]["schema_version"] == "1.0"
    assert result["verdict_effect"] == "informational_only"


def test_openai_client_extracts_real_envelope_without_logging_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "sandbox-configured-model"
        return httpx.Response(200, json={"choices": [{"message": {"content": _valid_raw("p")}}]})

    client = SandboxVLMClient(_config(), transport=httpx.MockTransport(handler))
    try:
        response = client.infer(
            case={
                "qc_point_id": "p",
                "name": "point",
                "category": "visual_defect",
                "criterion": "clean",
                "expected_behavior": "pass",
            },
            image_path=ROOT / "tests" / "fixtures" / "red_square.png",
            cv_result={"schema_version": "1.0"},
        )
    finally:
        client.close()
    assert json.loads(response.raw_output)["items"][0]["qc_point_id"] == "p"
    assert response.raw_output == response.parser_input


def test_inspection_client_preserves_raw_body_and_maps_strict_schema():
    body = {
        "detection_point_code": "p",
        "disposition": "reject_recommended",
        "observed_features": ["mark"],
        "defect_features": ["dark mark"],
        "normal_features_matched": [],
        "evidence_regions": [{"bbox": [1, 2, 3, 4]}],
        "confidence": 0.88,
        "uncertainty": "",
        "review_required_conditions": [],
        "provider": "configured-provider",
        "model": "sandbox-configured-model",
    }
    raw_body = json.dumps(body, separators=(",", ":"))
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text=raw_body, headers={"content-type": "application/json"})
    )
    client = SandboxVLMClient(
        _config(api_style="inspection", inference_path="/v1/inspect"),
        transport=transport,
    )
    try:
        response = client.infer(
            case={
                "qc_point_id": "p",
                "name": "point",
                "category": "visual_defect",
                "criterion": "clean",
                "expected_behavior": "reject mark",
            },
            image_path=ROOT / "tests" / "fixtures" / "red_square.png",
            cv_result={"schema_version": "1.0"},
        )
    finally:
        client.close()
    assert response.raw_output == raw_body
    parsed = parse_strict_sandbox_output(response.parser_input, expected_qc_point_ids=["p"])
    assert parsed.verdict == "reject"
    assert parsed.parsed_result["items"][0]["result"] == "fail"


def test_fault_injection_cases_reject_and_are_explicitly_labeled():
    cases = load_cases(CASES)
    selected = [case for case in cases if case["case_type"] != "real_inference"]
    client = SandboxVLMClient(
        _config(),
        transport=httpx.MockTransport(lambda request: pytest.fail("network must not be called")),
    )
    try:
        results = [execute_case(case, client=client) for case in selected]
    finally:
        client.close()
    assert len(results) >= 3
    assert all(result["verdict"] == "reject" and result["passed"] for result in results)
    assert all(
        all(flag.startswith("NON-PRODUCTION MOCK —") for flag in result["mock_flags"])
        for result in results
    )


def test_report_schema_markdown_and_address_redaction(tmp_path):
    cases = load_cases(CASES)
    result = {
        "case_id": "visual_defect-positive-01",
        "case_type": "real_inference",
        "category": "visual_defect",
        "input_ref": "tests/fixtures/red_square.png",
        "raw_model_output": _valid_raw("stage1_visual_defect"),
        "parsed_result": {"overall_result": "pass"},
        "verdict": "pass",
        "timing_ms": {"cv": 1.0, "inference": 2.0, "parse": 1.0, "total": 4.0},
        "passed": True,
        "anomaly_notes": ["think_tags_stripped"],
        "mock_flags": ["NON-PRODUCTION MOCK — fixture capture."],
        "think_tags_stripped": True,
    }
    report = build_report(_config(), cases, [result])
    assert report["schema_version"] == REPORT_SCHEMA_VERSION
    assert report["environment_declaration"] == SANDBOX_DECLARATION
    assert_report_has_no_server_address(report, _config())
    json_path, markdown_path = write_reports(report, tmp_path / "stage1_report.json")
    assert json.loads(json_path.read_text())["stage"] == 1
    assert SANDBOX_DECLARATION in markdown_path.read_text()
    assert "sandbox.invalid" not in render_markdown(report)


def test_report_address_leak_is_refused():
    report = {
        "raw": "sandbox.invalid",
    }
    with pytest.raises(ValueError, match="address leak"):
        assert_report_has_no_server_address(report, _config())


def test_runtime_env_requires_restricted_permissions_and_allowed_keys(tmp_path, monkeypatch):
    runtime = tmp_path / ".env.stage1.local"
    runtime.write_text(
        "QC_DB_URL=mysql+pymysql://configured.invalid/db\n"
        f"SAMPLE_STORE_DIR={tmp_path}/data/samples\n"
        f"CAPTURE_DIR={tmp_path}/data/captures\n"
        f"STAGE1_DATA_ROOT={tmp_path}/data\n",
        encoding="utf-8",
    )
    runtime.chmod(0o644)
    with pytest.raises(ArchitectureVerificationError, match="permissions"):
        load_runtime_env_file(runtime)
    runtime.chmod(0o600)
    for key in ("QC_DB_URL", "SAMPLE_STORE_DIR", "CAPTURE_DIR", "STAGE1_DATA_ROOT"):
        monkeypatch.delenv(key, raising=False)
    load_runtime_env_file(runtime)
    assert os.environ["QC_DB_URL"].startswith("mysql+pymysql://")


def test_architecture_gate_requires_all_endpoint_free_evidence():
    evidence = {
        "ready": True,
        "source_checkout_present": True,
        "data_root_within_checkout": True,
        "data_root_writable": True,
        "sample_and_capture_paths_within_data_root": True,
        "database_reachable": True,
        "database_schema_initialized": True,
        "database_endpoint_redacted": True,
    }
    assert architecture_ready(evidence)
    evidence["database_reachable"] = False
    assert not architecture_ready(evidence)


def test_architecture_write_probe_never_deletes_preexisting_file(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    data = root / "data"
    samples = data / "samples"
    captures = data / "captures"
    data.mkdir(parents=True)
    (root / ".git").mkdir()
    probe = data / ".stage1-write-probe"
    probe.write_text("keep", encoding="utf-8")
    monkeypatch.setenv("QC_DB_URL", "mysql+pymysql://configured.invalid/db")
    monkeypatch.setenv("STAGE1_DATA_ROOT", str(data))
    monkeypatch.setenv("SAMPLE_STORE_DIR", str(samples))
    monkeypatch.setenv("CAPTURE_DIR", str(captures))
    with pytest.raises(ArchitectureVerificationError, match="write_check_failed"):
        verify_architecture(root)
    assert probe.read_text(encoding="utf-8") == "keep"
