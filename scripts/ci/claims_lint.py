#!/usr/bin/env python3
"""No-unverified-claims check (CI_AND_MERGE_INSTRUCTIONS.md §1.4).

Scans repo documentation for readiness claims ("production-ready",
"real inference working", "PRD complete", ...) and requires each to sit
adjacent (within EVIDENCE_WINDOW lines) to a reference to concrete evidence —
a test report path, device log, CI run URL, or similar.

Per the CI instructions this is a SOFT check: it emits GitHub warning
annotations and a summary, and its workflow job runs with continue-on-error,
so it informs review rather than hard-blocking a merge. Exit code is non-zero
when unbacked claims are found so the annotation is visible.

Run:  python scripts/ci/claims_lint.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

CLAIM = re.compile(
    r"production[- ]ready"
    r"|real\s+inference\s+(?:is\s+)?working"
    r"|PRD[- ]complete"
    r"|fully\s+production"
    r"|ready\s+for\s+production",
    re.IGNORECASE,
)

# What counts as pointing at evidence: a link, a repo path to a report/log,
# or an explicit evidence/report reference.
EVIDENCE = re.compile(
    r"https?://"
    r"|\b[\w./-]+\.(?:log|md|txt|json|xml)\b"
    r"|\bevidence\b|\btest report\b|\bdevice log\b|\bCI run\b",
    re.IGNORECASE,
)

# Lines that *negate* a claim ("not production-ready", "is NOT production
# ready") are not claims.
NEGATION = re.compile(r"\b(not|never|no|isn't|aren't|without)\b[^.]{0,40}$", re.IGNORECASE)

EVIDENCE_WINDOW = 3  # lines before/after the claim


def scan_file(path: Path) -> list[tuple[int, str]]:
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    unbacked: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        m = CLAIM.search(line)
        if not m:
            continue
        prefix = line[: m.start()]
        if NEGATION.search(prefix):
            continue
        lo = max(0, i - EVIDENCE_WINDOW)
        hi = min(len(lines), i + EVIDENCE_WINDOW + 1)
        window = "\n".join(lines[lo:i] + [line[m.end():]] + lines[i + 1 : hi])
        if EVIDENCE.search(window):
            continue
        unbacked.append((i + 1, line.strip()))
    return unbacked


def main() -> int:
    md_files = sorted(
        p
        for p in REPO_ROOT.rglob("*.md")
        if ".venv" not in p.parts and ".git" not in p.parts and "node_modules" not in p.parts
    )
    total = 0
    for path in md_files:
        rel = path.relative_to(REPO_ROOT)
        for lineno, line in scan_file(path):
            total += 1
            # GitHub Actions warning annotation format.
            print(
                f"::warning file={rel},line={lineno}::Unbacked readiness claim "
                f"(needs adjacent evidence link/report): {line}"
            )
    if total:
        print(f"\nno-unverified-claims check: {total} claim(s) without adjacent evidence.")
        print("Each 'production-ready' / 'real inference working' / 'PRD complete' style")
        print("claim must reference the evidence backing it (test report, device log, CI run).")
        return 1
    print("no-unverified-claims check passed: no unbacked readiness claims found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
