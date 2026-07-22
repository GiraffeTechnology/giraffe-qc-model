#!/usr/bin/env python3
"""Stage 3 A/B report check (HARD gate).

Validates every ``sandbox_tests/reports/stage3_ab_*.json`` against the rules
in ``sandbox_tests/reports/stage3_ab_report.schema.json`` /
``docs/STAGE3_AB_TESTING_SPEC.md`` §3. No ``jsonschema`` dependency is used
(this repo is stdlib-first for CI scripts); the checks below are a direct,
readable transcription of the schema's constraints:

* ``stage3_group`` is ``"A"`` — Group B (remote VLM) was decommissioned
  2026-07-22 (spec §0) and is no longer a valid value.
* ``cv_execution_location`` is always ``"jetson_local"``.
* ``vlm_execution_location`` is always ``"jetson_local"``.
* ``model.{provider,name,revision,quantization,backend,manifest_sha256}`` are
  all present, non-empty, and ``manifest_sha256`` is a real 64-hex-char
  digest — not a placeholder.
* ``production_eligible`` is ``false`` — a Stage 3 report can never
  self-declare production eligibility.
* If present, ``hardware_validation_status`` is ``not_run`` or ``passed``
  (this script does not and cannot flip it — that requires the reviewed
  manual procedure in ``jetson_runner/HARDWARE_VALIDATION.md``).

Also reuses ``report_evidence_check``'s stage>=2 acceptance rule (real
model_call_count, not mock-only) since Stage 3 reports are stage 3.

Run:  python scripts/ci/stage3_ab_report_check.py
Exit: 0 clean (including zero reports found), 1 violations, 2 unreadable report.
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "sandbox_tests" / "reports"
REPORT_GLOB = "stage3_ab_*.json"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MODEL_FIELDS = ("provider", "name", "revision", "quantization", "backend", "manifest_sha256")
_BACKENDS = {"cpu", "cuda", "opencl", "hybrid_cpu_cuda"}


def check_report(path: Path, report: dict) -> list[str]:
    problems: list[str] = []
    rel = path.relative_to(REPO_ROOT)

    group = report.get("stage3_group")
    if group != "A":
        problems.append(
            f"{rel}: stage3_group is {group!r}, must be 'A' "
            "(Group B / remote VLM was decommissioned 2026-07-22)"
        )
        group = None

    if report.get("cv_execution_location") != "jetson_local":
        problems.append(
            f"{rel}: cv_execution_location is {report.get('cv_execution_location')!r}, "
            "must be 'jetson_local'"
        )

    vlm_loc = report.get("vlm_execution_location")
    if vlm_loc != "jetson_local":
        problems.append(
            f"{rel}: vlm_execution_location is {vlm_loc!r}, must be 'jetson_local'"
        )

    model = report.get("model")
    if not isinstance(model, dict):
        problems.append(f"{rel}: 'model' block is missing or not an object")
        model = {}
    for field in _MODEL_FIELDS:
        value = model.get(field)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{rel}: model.{field} is missing or empty")
    backend = model.get("backend")
    if isinstance(backend, str) and backend not in _BACKENDS:
        problems.append(f"{rel}: model.backend {backend!r} not in {sorted(_BACKENDS)}")
    digest = model.get("manifest_sha256")
    if isinstance(digest, str) and digest and not _HEX64.match(digest):
        problems.append(f"{rel}: model.manifest_sha256 is not a 64-hex-char digest: {digest!r}")

    if report.get("production_eligible") is not False:
        problems.append(
            f"{rel}: production_eligible is {report.get('production_eligible')!r}, "
            "must be exactly false"
        )

    hv_status = report.get("hardware_validation_status")
    if hv_status is not None and hv_status not in ("not_run", "passed"):
        problems.append(f"{rel}: hardware_validation_status {hv_status!r} not in ('not_run', 'passed')")

    # Reuse the stage>=2 acceptance rule (real calls, not mock-only) for any
    # report claiming status == "passed".
    report_check = _load_report_evidence_check()
    problems.extend(report_check.check_report(path, report))

    return problems


def _load_report_evidence_check():
    path = REPO_ROOT / "scripts" / "ci" / "report_evidence_check.py"
    spec = importlib.util.spec_from_file_location("report_evidence_check", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    if not REPORTS_DIR.is_dir():
        print(f"no reports directory at {REPORTS_DIR}, nothing to check")
        return 0

    reports = sorted(
        p for p in REPORTS_DIR.glob(REPORT_GLOB) if not p.name.endswith(".schema.json")
    )
    if not reports:
        print(f"no {REPORT_GLOB} reports found — nothing to check yet")
        return 0

    problems: list[str] = []
    for path in reports:
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
        print("Stage 3 A/B report check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"Stage 3 A/B report check passed: {len(reports)} report(s) checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
