"""The CI evidence gates exist so green tests can never masquerade as PRD
delivery: a stage report cannot claim acceptance without real model calls, and
a traceability-matrix row that requires a real run cannot be 'verified' by
unit tests alone."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(module_path: str):
    path = REPO_ROOT / module_path
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


report_check = _load("scripts/ci/report_evidence_check.py")
trace_check = _load("scripts/ci/prd_traceability_check.py")


# ── report_evidence_check ─────────────────────────────────────────────────────


def _report(**overrides) -> dict:
    base = {
        "stage": 2,
        "status": "passed",
        "summary": {"model_call_count": 3},
        "acceptance": {},
        "cases": [{"case_id": "c1", "mock_flag": False}],
    }
    base.update(overrides)
    return base


def test_current_repo_reports_are_clean():
    assert report_check.main() == 0


def test_stage2_pass_with_zero_model_calls_is_rejected():
    problems = report_check.check_report(
        report_check.REPORTS_DIR / "x.json",
        _report(summary={"model_call_count": 0}),
    )
    assert any("zero real model calls" in p for p in problems)


def test_stage2_pass_without_model_call_count_is_rejected():
    problems = report_check.check_report(
        report_check.REPORTS_DIR / "x.json", _report(summary={})
    )
    assert any("model_call_count is missing" in p for p in problems)


def test_stage2_pass_with_all_mock_cases_is_rejected():
    problems = report_check.check_report(
        report_check.REPORTS_DIR / "x.json",
        _report(cases=[{"case_id": "c1", "mock_flag": True}]),
    )
    assert any("mock_flag=true" in p for p in problems)


def test_stage3_entry_flag_needs_pass_and_model_evidence():
    problems = report_check.check_report(
        report_check.REPORTS_DIR / "x.json",
        _report(
            status="historical_fixture_suite_only",
            acceptance={"passed_for_stage3_entry": True},
        ),
    )
    assert any("passed_for_stage3_entry" in p for p in problems)


def test_stage1_pass_without_model_calls_is_allowed():
    problems = report_check.check_report(
        report_check.REPORTS_DIR / "x.json",
        _report(stage=1, summary={}),
    )
    assert problems == []


def test_unknown_status_is_rejected():
    problems = report_check.check_report(
        report_check.REPORTS_DIR / "x.json", _report(status="totally_fine")
    )
    assert any("unknown status" in p for p in problems)


# ── prd_traceability_check ────────────────────────────────────────────────────


def _matrix(entry_overrides: dict) -> dict:
    entry = {
        "id": "PRD-T-01",
        "requirement": "示例要求",
        "status": "verified",
        "requires_real_run": False,
        "code_evidence": ["src/api/main.py"],
        "test_evidence": ["tests/test_web_shell.py"],
        "real_run_evidence": None,
    }
    entry.update(entry_overrides)
    return {"requirements": [entry]}


def test_committed_matrix_is_valid():
    matrix = json.loads(
        (REPO_ROOT / "sandbox_tests" / "prd_traceability.json").read_text()
    )
    assert trace_check.check(matrix) == []


def test_verified_real_run_requirement_needs_artifact():
    problems = trace_check.check(_matrix({"requires_real_run": True}))
    assert any("green tests alone" in p for p in problems)


def test_verified_real_run_with_existing_artifact_is_accepted():
    problems = trace_check.check(
        _matrix(
            {
                "requires_real_run": True,
                "real_run_evidence": "sandbox_tests/reports/stage1_report.json",
            }
        )
    )
    assert problems == []


def test_missing_evidence_path_is_rejected():
    problems = trace_check.check(
        _matrix({"test_evidence": ["tests/does_not_exist.py"]})
    )
    assert any("does not exist" in p for p in problems)


def test_nonverified_entry_must_state_gap():
    problems = trace_check.check(
        _matrix({"status": "partial", "requires_real_run": False})
    )
    assert any("'gap'" in p for p in problems)


def test_unknown_matrix_status_is_rejected():
    problems = trace_check.check(_matrix({"status": "done"}))
    assert any("unknown status" in p for p in problems)
