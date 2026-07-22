#!/usr/bin/env python3
"""Sensitive deployment info lint (HARD gate).

P0 remediation (2026-07-22): real device hostnames and internal LAN
addresses were found committed in tracked docs (e.g. a cloud host codename,
a Jetson device hostname, its LAN IP). Those were scrubbed from the current
tree. This lint is the regression guard: it fails CI if any of those exact
literal strings reappear anywhere in a tracked text file.

This is deliberately a small, explicit denylist of known-sensitive literals
rather than a general IP/hostname pattern scanner — a pattern scanner would
flag the many legitimate documented example addresses already used
throughout the repo (e.g. 192.168.1.10 as a stable test fixture) and train
reviewers to ignore its noise. A denylist of specific real identifiers stays
precise and only grows when a real leak is found and fixed.

Run:  python scripts/ci/sensitive_info_lint.py
Exit: 0 clean, 1 a denylisted string was found.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Exact literal strings that must never appear in a tracked file again.
# Keep this list to real identifiers found and removed, not general patterns.
_DENYLIST = (
    "abcdYi",
    "GiraffeNVIDIA",
    "192.168.5.35",
)

# This lint script's own docstring/denylist necessarily contains the strings
# it's watching for; exclude it from the scan.
_SELF = Path(__file__).resolve()

# Binary / generated paths that would produce noise or false positives.
_EXCLUDE_DIR_PARTS = (".git", ".venv", "__pycache__", "node_modules")

# LICENSE names "abcdYi" as a Giraffe-family product in its API/integration
# boundary clause (§5) — a legal/product reference, not an infrastructure
# hostname leak. Editing legal text is outside this lint's scope; flagged for
# human review instead of auto-excluded silently.
_KNOWN_EXCEPTIONS = {"LICENSE"}


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.check_output(
            ["git", "ls-files"], cwd=REPO_ROOT, text=True
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"error: cannot list tracked files: {exc}", file=sys.stderr)
        return []
    return [REPO_ROOT / line for line in out.splitlines() if line]


def scan() -> tuple[list[str], list[str]]:
    """Returns (hard_problems, informational_notes)."""
    problems: list[str] = []
    notes: list[str] = []
    for path in _tracked_files():
        if path.resolve() == _SELF:
            continue
        if any(part in _EXCLUDE_DIR_PARTS for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, IsADirectoryError):
            continue
        rel = path.relative_to(REPO_ROOT)
        for needle in _DENYLIST:
            if needle in text:
                line_no = next(
                    (i + 1 for i, line in enumerate(text.splitlines()) if needle in line),
                    None,
                )
                entry = f"{rel}:{line_no}: contains denylisted string {needle!r}"
                if str(rel) in _KNOWN_EXCEPTIONS:
                    notes.append(entry + " (known exception — reviewed, not a hostname/IP leak)")
                else:
                    problems.append(entry)
    return problems, notes


def main() -> int:
    problems, notes = scan()
    for n in notes:
        print(f"[NOTE] {n}")
    if problems:
        print("Sensitive-info lint FAILED — denylisted deployment identifiers found:")
        for p in problems:
            print(f"  - {p}")
        print(
            "\nRemove or redact these before committing. See the P0 remediation "
            "in docs/STAGE3_AB_TESTING_SPEC.md §6 (禁止事项)."
        )
        return 1
    print(f"Sensitive-info lint passed: {len(_DENYLIST)} denylisted string(s) not found in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
