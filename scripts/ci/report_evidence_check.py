#!/usr/bin/env python3
"""Report evidence check (HARD gate).

A stage report may never claim acceptance that its own recorded evidence does
not support. This enforces, for every ``sandbox_tests/reports/*.json``:

1. ``status`` must be a known value. ``passed`` claims acceptance; the
   withdrawn/historical statuses explicitly do not.
2. A ``passed`` report for stage >= 2 must record real model evidence:
   ``summary.model_call_count`` present and > 0. (Stage 1 is the CV-only
   sandbox stage and carries no model-call requirement.)
3. Any acceptance flag whose name references stage-3 entry may only be true in
   a ``passed`` report that satisfies rule 2 — a report with zero real model
   calls can never authorize Stage 3.
4. A ``passed`` report for stage >= 2 must not consist solely of mock cases:
   at least one case must have ``mock_flag`` false.

Run:  python scripts/ci/report_evidence_check.py
Exit: 0 clean, 1 violations, 2 unreadable report.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "sandbox_tests" / "reports"

# ``passed`` is the only status that claims acceptance. The rest either record
# failure or explicitly withdraw/limit the report's claims.
KNOWN_STATUSES = {
    "passed",
    "failed",
    "blocked",
    "superseded_acceptance_stopped",
    "historical_fixture_suite_only",
}


def _model_call_count(report: dict) -> int | None:
    summary = report.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("model_call_count"), int):
        return summary["model_call_count"]
    if isinstance(report.get("model_call_count"), int):
        return report["model_call_count"]
    return None


def check_report(path: Path, report: dict) -> list[str]:
    problems: list[str] = []
    rel = path.relative_to(REPO_ROOT)
    status = report.get("status")
    stage = report.get("stage")

    if status not in KNOWN_STATUSES:
        problems.append(f"{rel}: unknown status {status!r}")
        return problems

    claims_pass = status == "passed"
    calls = _model_call_count(report)

    if claims_pass and isinstance(stage, int) and stage >= 2:
        if calls is None:
            problems.append(
                f"{rel}: status 'passed' at stage {stage} but summary.model_call_count is missing"
            )
        elif calls <= 0:
            problems.append(
                f"{rel}: status 'passed' at stage {stage} with model_call_count={calls} — "
                "zero real model calls cannot support an acceptance claim"
            )
        cases = report.get("cases") or []
        if cases and all(c.get("mock_flag") for c in cases if isinstance(c, dict)):
            problems.append(
                f"{rel}: status 'passed' at stage {stage} but every case is mock_flag=true"
            )

    acceptance = report.get("acceptance")
    if isinstance(acceptance, dict):
        for key, value in acceptance.items():
            if "stage3" in key.replace("_", "").lower() and value is True:
                if not claims_pass:
                    problems.append(
                        f"{rel}: acceptance[{key!r}] is true but status is {status!r}"
                    )
                elif calls is None or calls <= 0:
                    problems.append(
                        f"{rel}: acceptance[{key!r}] is true without real model-call evidence"
                    )
    return problems


def main() -> int:
    if not REPORTS_DIR.is_dir():
        print(f"no reports directory at {REPORTS_DIR}, nothing to check")
        return 0
    problems: list[str] = []
    for path in sorted(REPORTS_DIR.glob("*.json")):
        if path.name.endswith(".schema.json"):
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"error: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        if not isinstance(report, dict):
            problems.append(f"{path.relative_to(REPO_ROOT)}: report is not a JSON object")
            continue
        problems.extend(check_report(path, report))

    if problems:
        print("Report evidence check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("Report evidence check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
