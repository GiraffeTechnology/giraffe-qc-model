#!/usr/bin/env python3
"""Mock-labeling lint (CI_AND_MERGE_INSTRUCTIONS.md §1.3).

The 2026-07-12 delivery audit's REJECT verdict was driven by mock behavior
masquerading as real functionality. This lint makes that regression impossible
to reintroduce silently: any *production-path* file that contains mock/fake
patterns must carry an explicit, unmistakable non-production label.

Rules
-----
1. Scanned trees (production paths):
       src/, edge_cv_agent/app/, apps/android-qc/app/src/main/
   Test trees (tests/, */tests/, src/test/) are exempt — mocks belong there.
2. A file "contains mock patterns" when it matches MOCK_PATTERNS below
   (class/function/identifier names, not prose).
3. Such a file passes only if it contains the marker line
       NON-PRODUCTION MOCK
   (case-insensitive, anywhere in the file, normally in the module docstring
   or file-header comment) explaining that the code is a labeled mock.
4. Anything else fails the build, printing every offending file/line.

Run:  python scripts/ci/mock_labeling_lint.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_ROOTS = [
    "src",
    "edge_cv_agent/app",
    "apps/android-qc/app/src/main",
]

# Directories under a scan root that are still test-only and therefore exempt.
EXEMPT_DIR_PARTS = {"tests", "test", "androidTest"}

SUFFIXES = {".py", ".kt", ".java", ".cpp", ".html", ".js"}

MARKER = re.compile(r"non-production\s+mock", re.IGNORECASE)

# Identifier-shaped mock/fake patterns (from CI_AND_MERGE_INSTRUCTIONS.md §1.3,
# plus the concrete names present in this repo). Prose words like "mocked" in a
# comment do not match; identifiers and snake/camel-case names do.
MOCK_PATTERNS = re.compile(
    r"""
    \bmock_result\b
    | \bMockPad\w*\b
    | \bMockCV\w*\b
    | \bMockProvider\b
    | \bMock[A-Z]\w+\b          # MockTargetDetector, MockCameraFrameSource, ...
    | \bFake[A-Z]\w+\b          # FakeSkuRepository, FakeQwenProvider, ...
    | \bfake_(?:pass|response|provider|verdict)\w*\b
    | \bmock_(?:scenario|pipeline|provider|edge_cv|pass)\w*\b
    | \brun_mock_\w+\b
    """,
    re.VERBOSE,
)


def is_exempt(path: Path) -> bool:
    return bool(EXEMPT_DIR_PARTS.intersection(path.parts))


def main() -> int:
    failures: list[str] = []
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            rel = path.relative_to(REPO_ROOT)
            if is_exempt(rel):
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            hits = [
                (i, line.strip())
                for i, line in enumerate(text.splitlines(), 1)
                if MOCK_PATTERNS.search(line)
            ]
            if not hits:
                continue
            if MARKER.search(text):
                continue  # explicitly labeled — allowed
            for lineno, line in hits[:5]:
                failures.append(f"{rel}:{lineno}: {line}")
            if len(hits) > 5:
                failures.append(f"{rel}: ... and {len(hits) - 5} more matches")

    if failures:
        print("mock-labeling lint FAILED — mock/fake patterns in production paths")
        print("without an explicit 'NON-PRODUCTION MOCK' label:\n")
        print("\n".join(failures))
        print(
            "\nFix: either remove the mock from the production path, or add a"
            "\nfile-header/docstring line containing 'NON-PRODUCTION MOCK' that"
            "\nexplains why the mock is retained (CI fallback, labeled dev mode, ...)."
        )
        return 1
    print("mock-labeling lint passed: all mock/fake patterns in production paths are labeled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
