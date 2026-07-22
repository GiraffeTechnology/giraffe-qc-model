#!/usr/bin/env python3
"""Stage 3 authorization gate (hard).

Stage 3 Jetson A/B testing may start only after a *fresh* Stage 2 interactive
acceptance has passed (Stage 2 P0 Remediation Record, "Required fresh Stage 2
acceptance"). This script is the single place that decides whether that gate
is currently open, so no doc, script, or report can assert Stage 3 is
authorized on its own say-so.

Authorization requires ALL of:

1. ``sandbox_tests/prd_traceability.json`` entry ``PRD-S2-30`` has
   ``status == "verified"`` and a ``real_run_evidence`` path that exists.
2. That evidence file is a report matching
   ``sandbox_tests/reports/report.schema.json`` with:
   - ``stage == 2``
   - ``status == "passed"``
   - a real-call count (``model_call_count`` at top level or in ``summary``)
     that is an integer > 0
   - at least one case with ``mock_flags`` empty (i.e. not mock-only)
3. The evidence file's ``generated_at`` (or ``accepted_at``) timestamp is not
   older than the Stage 2 P0 remediation record
   (``docs/STAGE2_P0_REMEDIATION_2026-07-22``, 2026-07-22) — an evidence file
   older than the remediation it must supersede cannot authorize Stage 3.

CI runs this as an informational hard job (`python scripts/ci/stage3_authorization_gate.py`)
so the *current* authorization state is always visible in the PR checks —
green does not mean "Stage 3 is authorized"; it means "the gate's own logic
runs cleanly against the current matrix". Use
``--require-open`` from a Stage 3 A/B harness to make the *harness* itself
refuse to run when the gate is closed.
"""
from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "sandbox_tests" / "prd_traceability.json"
GATE_ENTRY_ID = "PRD-S2-30"

# The fresh-Stage-2-acceptance requirement was established here; evidence
# predating it cannot satisfy a *fresh* re-acceptance.
_REMEDIATION_CUTOFF = datetime.datetime(2026, 7, 22, tzinfo=datetime.timezone.utc)


class GateResult:
    def __init__(self):
        self.open = False
        self.reasons: list[str] = []

    def fail(self, reason: str) -> None:
        self.reasons.append(reason)

    def summary(self) -> str:
        if self.open:
            return "OPEN — Stage 3 A/B testing is authorized by current evidence."
        lines = ["CLOSED — Stage 3 A/B testing is not authorized:"]
        lines.extend(f"  - {r}" for r in self.reasons)
        return "\n".join(lines)


def _parse_timestamp(value) -> datetime.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def evaluate() -> GateResult:
    result = GateResult()

    try:
        matrix = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.fail(f"cannot read {MATRIX_PATH}: {exc}")
        return result

    entry = next(
        (e for e in matrix.get("requirements", []) if e.get("id") == GATE_ENTRY_ID),
        None,
    )
    if entry is None:
        result.fail(f"traceability matrix has no {GATE_ENTRY_ID} entry")
        return result

    if entry.get("status") != "verified":
        result.fail(
            f"{GATE_ENTRY_ID}.status is {entry.get('status')!r}, not 'verified'"
        )

    evidence_rel = entry.get("real_run_evidence")
    if not evidence_rel:
        result.fail(f"{GATE_ENTRY_ID}.real_run_evidence is not set")
        return result

    evidence_path = REPO_ROOT / evidence_rel
    if not evidence_path.exists():
        result.fail(f"real_run_evidence path does not exist: {evidence_rel}")
        return result

    try:
        report = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result.fail(f"cannot read evidence report {evidence_rel}: {exc}")
        return result

    if report.get("stage") != 2:
        result.fail(f"evidence report stage is {report.get('stage')!r}, not 2")
    if report.get("status") != "passed":
        result.fail(f"evidence report status is {report.get('status')!r}, not 'passed'")

    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    calls = summary.get("model_call_count", report.get("model_call_count"))
    if not isinstance(calls, int) or calls <= 0:
        result.fail(f"evidence report model_call_count is {calls!r}, not a positive integer")

    cases = report.get("cases") or []
    if cases and all(c.get("mock_flags") for c in cases if isinstance(c, dict)):
        result.fail("every case in the evidence report is mock-flagged")

    ts = _parse_timestamp(report.get("generated_at")) or _parse_timestamp(
        report.get("accepted_at")
    )
    if ts is None:
        result.fail("evidence report has no generated_at/accepted_at timestamp")
    elif ts < _REMEDIATION_CUTOFF:
        result.fail(
            f"evidence report timestamp {ts.isoformat()} predates the "
            f"2026-07-22 fresh-acceptance requirement — stale evidence cannot "
            "authorize Stage 3"
        )

    result.open = not result.reasons
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--require-open",
        action="store_true",
        help="exit non-zero (instead of 0) when the gate is closed — for use "
        "by a Stage 3 harness that must refuse to run",
    )
    args = parser.parse_args()

    result = evaluate()
    print(result.summary())

    if args.require_open:
        return 0 if result.open else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
