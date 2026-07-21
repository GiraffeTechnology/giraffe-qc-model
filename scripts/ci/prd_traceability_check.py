#!/usr/bin/env python3
"""PRD traceability check (HARD gate).

Validates ``sandbox_tests/prd_traceability.json`` — the machine-readable
version of the Stage 2 PRD gap-audit matrix — so a requirement can never be
promoted to "verified" on green unit tests alone:

* every entry needs a unique id, a known status, and existing
  ``code_evidence`` / ``test_evidence`` repo paths;
* ``verified`` requires at least one code and one test evidence path;
* an entry with ``requires_real_run: true`` may only be ``verified`` when
  ``real_run_evidence`` names an existing artifact (report/log) in the repo;
* non-verified entries must state their ``gap`` or carry
  ``requires_real_run: true`` so the missing step is explicit.

Run:  python scripts/ci/prd_traceability_check.py
Exit: 0 clean, 1 violations, 2 unreadable matrix.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "sandbox_tests" / "prd_traceability.json"

STATUSES = {"verified", "implemented_unverified", "partial", "missing"}


def check(matrix: dict) -> list[str]:
    problems: list[str] = []
    entries = matrix.get("requirements")
    if not isinstance(entries, list) or not entries:
        return ["matrix has no 'requirements' list"]

    seen_ids: set[str] = set()
    for entry in entries:
        eid = entry.get("id", "<missing id>")
        if eid in seen_ids:
            problems.append(f"{eid}: duplicate id")
        seen_ids.add(eid)

        status = entry.get("status")
        if status not in STATUSES:
            problems.append(f"{eid}: unknown status {status!r}")
            continue

        for kind in ("code_evidence", "test_evidence"):
            paths = entry.get(kind) or []
            if not isinstance(paths, list):
                problems.append(f"{eid}: {kind} must be a list")
                continue
            for rel in paths:
                if not (REPO_ROOT / rel).exists():
                    problems.append(f"{eid}: {kind} path does not exist: {rel}")

        real_run = entry.get("real_run_evidence")
        requires_real_run = bool(entry.get("requires_real_run"))

        if status == "verified":
            if not entry.get("code_evidence"):
                problems.append(f"{eid}: verified without code_evidence")
            if not entry.get("test_evidence"):
                problems.append(f"{eid}: verified without test_evidence")
            if requires_real_run:
                if not real_run:
                    problems.append(
                        f"{eid}: verified with requires_real_run=true but no "
                        "real_run_evidence — green tests alone cannot verify a "
                        "real-run requirement"
                    )
                elif not (REPO_ROOT / real_run).exists():
                    problems.append(
                        f"{eid}: real_run_evidence does not exist: {real_run}"
                    )
        else:
            if not requires_real_run and not entry.get("gap"):
                problems.append(
                    f"{eid}: status {status!r} must state its 'gap' or set "
                    "requires_real_run=true"
                )
        if real_run and not (REPO_ROOT / real_run).exists():
            problems.append(f"{eid}: real_run_evidence does not exist: {real_run}")

    return problems


def main() -> int:
    try:
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {MATRIX_PATH}: {exc}", file=sys.stderr)
        return 2

    problems = check(matrix)
    if problems:
        print("PRD traceability check FAILED:")
        for p in problems:
            print(f"  - {p}")
        return 1
    entries = matrix["requirements"]
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["status"]] = counts.get(e["status"], 0) + 1
    print(
        f"PRD traceability check passed: {len(entries)} requirements "
        + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
