"""Stable machine/human report writers shared by all sandbox stages."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sandbox_tests.common import SANDBOX_DECLARATION


REPORT_SCHEMA_VERSION = "sandbox-qc-report-v1"


def write_reports(report: dict[str, Any], json_path: str | Path) -> tuple[Path, Path]:
    _validate_report(report)
    destination = Path(json_path)
    markdown = destination.with_suffix(".md")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown.write_text(render_markdown(report), encoding="utf-8")
    return destination, markdown


def _validate_report(report: dict[str, Any]) -> None:
    required = {
        "schema_version",
        "stage",
        "status",
        "environment_declaration",
        "model_delta_note",
        "cases",
        "summary",
        "acceptance",
    }
    missing = sorted(required - report.keys())
    if missing:
        raise ValueError(f"report missing fields: {missing}")
    if report["schema_version"] != REPORT_SCHEMA_VERSION:
        raise ValueError("unsupported sandbox report schema")
    if report["environment_declaration"] != SANDBOX_DECLARATION:
        raise ValueError("mandatory sandbox declaration changed")
    if not isinstance(report["cases"], list):
        raise ValueError("report cases must be an array")
    case_required = {
        "case_id",
        "category",
        "input_ref",
        "raw_model_output",
        "parsed_result",
        "verdict",
        "timing_ms",
        "passed",
        "anomaly_notes",
        "mock_flags",
    }
    for case in report["cases"]:
        missing_case = sorted(case_required - case.keys())
        if missing_case:
            raise ValueError(f"case {case.get('case_id')} missing fields: {missing_case}")


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Sandbox QC Stage {report['stage']} Report",
        "",
        f"> {report['environment_declaration']}",
        "",
        f"> Model delta: {report['model_delta_note']}",
        "",
        f"**Status:** `{report['status']}`",
        "",
        "## Summary",
        "",
        "```json",
        json.dumps(report["summary"], ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
        "## Acceptance",
        "",
    ]
    for key, value in report["acceptance"].items():
        lines.append(f"- [{'x' if value else ' '}] `{key}`")
    if "architecture" in report:
        lines.extend(
            [
                "",
                "## Architecture evidence",
                "",
                "Endpoint and credential values are intentionally excluded.",
                "",
                "```json",
                json.dumps(report["architecture"], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
            ]
        )
    lines.extend(["", "## Cases", ""])
    for case in report["cases"]:
        lines.extend(
            [
                f"### {case['case_id']}",
                "",
                f"- Category: `{case['category']}`",
                f"- Input: `{case['input_ref']}`",
                f"- Verdict: `{case['verdict']}`",
                f"- Passed: `{str(case['passed']).lower()}`",
                f"- Timings (ms): `{json.dumps(case['timing_ms'], sort_keys=True)}`",
                f"- Anomalies: `{json.dumps(case['anomaly_notes'], ensure_ascii=False)}`",
                f"- Mock flags: `{json.dumps(case['mock_flags'], ensure_ascii=False)}`",
                "",
                "Raw model output:",
                "",
                "```text",
                case["raw_model_output"],
                "```",
                "",
                "Parsed result:",
                "",
                "```json",
                json.dumps(case["parsed_result"], ensure_ascii=False, indent=2, sort_keys=True),
                "```",
                "",
            ]
        )
    return "\n".join(lines) + "\n"
