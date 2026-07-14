"""Stage 2 gate entry point; simulator execution starts only after Q1."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from sandbox_tests.common import SANDBOX_DECLARATION
from sandbox_tests.reporting import REPORT_SCHEMA_VERSION, write_reports
from sandbox_tests.stage2.gate import Stage2DecisionRequired, Stage2Gate


MODEL_DELTA_NOTE = (
    "Stage 2 CV/UI simulation requires no real LLM/VLM call. Sandbox and "
    "production model selections remain replaceable configured defaults, not "
    "Giraffe product identity or ecosystem dependencies. This blocked report "
    "contains no model-quality evidence."
)


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        default="sandbox_tests/reports/stage2_report.json",
    )
    args = parser.parse_args(argv)
    try:
        gate = Stage2Gate.from_environment()
    except Stage2DecisionRequired as exc:
        json_path, markdown_path = write_reports(build_blocked_report(str(exc)), args.report)
        print(f"wrote {json_path} and {markdown_path}; status=blocked")
        return 2
    print(
        "Stage 2 Q1 gate accepted; simulator execution may proceed only with "
        f"method={gate.method} and the recorded external volume."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

